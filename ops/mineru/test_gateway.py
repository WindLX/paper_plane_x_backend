"""Run with the deployed MinerU Python: python -m unittest test_gateway.py."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

import gateway


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def check_idle(self, *, active=0, busy=False):
        controller = gateway.Gateway()
        controller.last_use = time.monotonic() - gateway.IDLE_SECONDS - 1
        controller.active = active
        controller.systemctl = AsyncMock(return_value="active\n")
        controller.jobs_busy = AsyncMock(return_value=busy)
        sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
        with patch.object(gateway.asyncio, "sleep", sleep):
            with self.assertRaises(asyncio.CancelledError):
                await controller.idle_monitor()
        return controller

    async def test_idle_stops_both_workers(self):
        controller = await self.check_idle()
        controller.systemctl.assert_any_await("stop", "mineru-web.service", "mineru-api.service")

    async def test_active_transfer_blocks_shutdown(self):
        controller = await self.check_idle(active=1)
        controller.systemctl.assert_not_awaited()

    async def test_detached_running_job_blocks_shutdown(self):
        controller = await self.check_idle(busy=True)
        self.assertEqual(controller.systemctl.await_count, 1)
        self.assertLess(time.monotonic() - controller.last_use, 1)

    async def test_failed_job_query_keeps_worker_running(self):
        controller = gateway.Gateway()
        controller.last_use -= gateway.IDLE_SECONDS + 1
        controller.systemctl = AsyncMock(return_value="active\n")
        controller.jobs_busy = AsyncMock(side_effect=RuntimeError("unavailable"))
        sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
        with patch.object(gateway.asyncio, "sleep", sleep), self.assertLogs("mineru-gateway", level="ERROR"):
            with self.assertRaises(asyncio.CancelledError):
                await controller.idle_monitor()
        self.assertEqual(controller.systemctl.await_count, 1)

    async def test_simultaneous_cold_requests_start_once(self):
        controller = gateway.Gateway()
        started = False
        async def ready(kind):
            return started
        async def control(*args):
            nonlocal started
            started = True
            return "active\n"
        controller.ready = AsyncMock(side_effect=ready)
        controller.systemctl = AsyncMock(side_effect=control)
        await asyncio.gather(controller.ensure("api"), controller.ensure("api"))
        controller.systemctl.assert_awaited_once_with("start", "--no-block", "mineru-api.service")


if __name__ == "__main__":
    unittest.main()
