#!/usr/bin/env python3
"""Wake MinerU on HTTP access and stop workers after an idle hour.

The gateway stays running without importing Torch. API jobs are checked before
shutdown, so queued jobs and work detached from an HTTP request keep the GPU alive.
"""

import asyncio
import logging
import os
import time

import aiohttp
from aiohttp import web

LOG = logging.getLogger("mineru-gateway")
IDLE_SECONDS = float(os.environ.get("MINERU_IDLE_SECONDS", "3600"))
START_TIMEOUT = float(os.environ.get("MINERU_START_TIMEOUT", "600"))
UPSTREAM = {"api": "http://127.0.0.1:17860", "web": "http://127.0.0.1:17861"}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}


class Gateway:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.last_use = time.monotonic()
        self.active = 0
        self.session = None

    async def systemctl(self, *args):
        process = await asyncio.create_subprocess_exec("systemctl", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError(f"systemctl {' '.join(args)}: {stderr.decode().strip()}")
        return stdout.decode()

    async def ready(self, kind):
        path = "/v1/health" if kind == "api" else "/"
        try:
            async with self.session.get(UPSTREAM[kind] + path, timeout=aiohttp.ClientTimeout(total=3)) as response:
                return response.status == 200
        except (aiohttp.ClientError, TimeoutError):
            return False

    async def ensure(self, kind):
        async with self.lock:
            for worker in (["api", "web"] if kind == "web" else ["api"]):
                if await self.ready(worker):
                    continue
                LOG.info("Starting MinerU %s", worker)
                await self.systemctl("start", "--no-block", f"mineru-{worker}.service")
                deadline = time.monotonic() + START_TIMEOUT
                while not await self.ready(worker):
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"MinerU {worker} startup timed out")
                    state = await self.systemctl("show", f"mineru-{worker}.service", "--property=ActiveState", "--value")
                    if state.strip() == "failed":
                        raise RuntimeError(f"MinerU {worker} failed; inspect journalctl -u mineru-{worker}")
                    await asyncio.sleep(1)

    async def jobs_busy(self):
        cursor = None
        while True:
            params = {"limit": "100"}
            if cursor:
                params["after"] = cursor
            async with self.session.get(UPSTREAM["api"] + "/v1/parse/jobs", params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                page = await response.json()
            if any(job["status"] in ("queued", "running") for job in page["data"]):
                return True
            if not page["has_more"]:
                return False
            cursor = page["last_id"]
            if not cursor:
                raise RuntimeError("Invalid MinerU job pagination")

    async def idle_monitor(self):
        while True:
            await asyncio.sleep(30)
            try:
                async with self.lock:
                    if self.active or time.monotonic() - self.last_use <= IDLE_SECONDS:
                        continue
                    state = await self.systemctl("show", "mineru-api.service", "--property=ActiveState", "--value")
                    if state.strip() == "active" and await self.jobs_busy():
                        self.last_use = time.monotonic()
                        continue
                    LOG.info("Idle for %.0fs; stopping MinerU workers", IDLE_SECONDS)
                    await self.systemctl("stop", "mineru-web.service", "mineru-api.service")
                    self.last_use = time.monotonic()
            except (aiohttp.ClientError, TimeoutError, RuntimeError, KeyError, ValueError):
                LOG.exception("Idle check failed; workers kept running")

    async def proxy(self, request):
        kind = request.app["kind"]
        # Gradio heartbeat/SSE keepalives do not represent active parsing.
        useful = (kind == "api" and request.path not in ("/v1/health", "/v1/models", "/v1/tiers")) or (kind == "web" and (request.path == "/" or (request.method == "POST" and "heartbeat" not in request.path)))
        if useful:
            self.active += 1
            self.last_use = time.monotonic()
        try:
            await self.ensure(kind)
            target = UPSTREAM[kind] + request.raw_path
            headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
            headers["X-Forwarded-Proto"] = request.scheme
            headers["X-Forwarded-For"] = request.remote or ""
            async with self.session.request(request.method, target, headers=headers, data=request.content.iter_chunked(65536), allow_redirects=False) as upstream:
                response = web.StreamResponse(status=upstream.status, headers={k: v for k, v in upstream.headers.items() if k.lower() not in HOP_HEADERS})
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                return response
        except (aiohttp.ClientError, TimeoutError, RuntimeError) as error:
            LOG.exception("MinerU proxy failed")
            return web.json_response({"error": str(error)}, status=503)
        finally:
            if useful:
                self.active -= 1
                self.last_use = time.monotonic()


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    gateway = Gateway()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10), auto_decompress=False) as session:
        gateway.session = session
        runners = []
        for kind, port in (("api", 7860), ("web", 7861)):
            app = web.Application(client_max_size=512 * 1024 * 1024)
            app["kind"] = kind
            app.router.add_route("*", "/{path:.*}", gateway.proxy)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", port).start()
            runners.append(runner)
        monitor = asyncio.create_task(gateway.idle_monitor())
        try:
            await asyncio.Event().wait()
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            for runner in runners:
                await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
