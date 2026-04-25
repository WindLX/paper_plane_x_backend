"""FastAPI 应用主入口."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from paper_plane_x_backend.api.routers import (
    agent_traces,
    data_process,
    hitl,
    librarian,
    paper,
    project,
)
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services import init_database
from paper_plane_x_backend.services.data_process_tasks.lifecycle import (
    start_worker_pool,
    stop_worker_pool,
)
from paper_plane_x_backend.utils.logging import (
    get_active_log_file_path,
    setup_logging,
)
from paper_plane_x_backend.version import get_app_version

setup_logging()
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    description="AI Agent-powered research survey data-process system",
    version=get_app_version(),
    debug=settings.debug,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(project.router, prefix="/api/v1")
app.include_router(paper.router, prefix="/api/v1")
app.include_router(agent_traces.router, prefix="/api/v1")
app.include_router(librarian.router, prefix="/api/v1")
app.include_router(data_process.router, prefix="/api/v1")
app.include_router(hitl.router, prefix="/api/v1")


def _resolve_console_dist_dir() -> Path | None:
    candidates = [
        settings.api.console_dist_dir,
        Path(__file__).resolve().parents[3] / "paper_plane_x_frontend" / "dist",
    ]
    for candidate in candidates:
        index_path = candidate / "index.html"
        if index_path.exists():
            return candidate.resolve()
    return None


def _serve_console_file(resource_path: str | None = None) -> FileResponse:
    console_dist_dir = _resolve_console_dist_dir()
    if console_dist_dir is None:
        raise HTTPException(status_code=404, detail="Console build not found")

    index_path = console_dist_dir / "index.html"
    if not resource_path:
        return FileResponse(index_path)

    # Backward compatibility for previously-built console assets with `/console/*` base.
    if resource_path == "console":
        return FileResponse(index_path)
    if resource_path.startswith("console/"):
        resource_path = resource_path[len("console/") :]

    candidate = (console_dist_dir / resource_path).resolve()
    try:
        candidate.relative_to(console_dist_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")

    if candidate.is_file():
        return FileResponse(candidate)

    return FileResponse(index_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动事件（Lifespan）."""
    settings.ensure_directories()
    init_database()
    await start_worker_pool()
    logger.info(
        "event=app.startup_completed log_file=%s",
        (
            str(get_active_log_file_path())
            if get_active_log_file_path() is not None
            else "disabled"
        ),
    )
    yield
    await stop_worker_pool()
    logger.info("event=app.shutdown_completed")


app.router.lifespan_context = lifespan


@app.get("/health")
async def health_check():
    """健康检查接口."""
    return {"status": "ok", "app_name": settings.app_name}


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/projects", status_code=307)


@app.get("/{resource_path:path}", include_in_schema=False)
async def console_fallback(resource_path: str) -> FileResponse:
    if resource_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_console_file(resource_path)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "paper_plane_x_backend.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
    )
