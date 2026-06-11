"""FastAPI 应用主入口."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from paper_plane_x_backend.api.routers import (
    agent_traces,
    conversation,
    conversation_ws,
    data_process,
    data_process_ws,
    hitl_ws,
    librarian,
    paper,
    project,
    project_files,
)
from paper_plane_x_backend.api.routers import (
    settings as settings_router,
)
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services import init_database
from paper_plane_x_backend.services.data_process_tasks.lifecycle import (
    start_worker_pool,
    stop_worker_pool,
)
from paper_plane_x_backend.services.database import get_db
from paper_plane_x_backend.services.project.files import get_project_file_manager
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
app.include_router(paper.router, prefix="/api/v1")
app.include_router(project.router, prefix="/api/v1")
app.include_router(agent_traces.router, prefix="/api/v1")
app.include_router(librarian.router, prefix="/api/v1")
app.include_router(data_process.router, prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")
app.include_router(conversation.router, prefix="/api/v1")
app.include_router(conversation_ws.router, prefix="/api/v1")
app.include_router(data_process_ws.router, prefix="/api/v1")
app.include_router(hitl_ws.router, prefix="/api/v1")
app.include_router(project_files.router, prefix="/api/v1")


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


_templates: Jinja2Templates | None = None


def _get_templates() -> Jinja2Templates | None:
    global _templates
    if _templates is not None:
        return _templates
    console_dist_dir = _resolve_console_dist_dir()
    if console_dist_dir is None:
        return None
    _templates = Jinja2Templates(directory=str(console_dist_dir))
    return _templates


def _get_public_base_url(request: Request) -> str:
    """获取客户端实际访问的 Base URL（支持 Nginx 等反向代理）."""
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_port = request.headers.get("x-forwarded-port")

    if forwarded_host:
        proto = forwarded_proto or "https"
        host = forwarded_host
        if forwarded_port and forwarded_port not in ("80", "443"):
            return f"{proto}://{host}:{forwarded_port}"
        return f"{proto}://{host}"

    return str(request.base_url).rstrip("/")


def _build_app_config_json(request: Request) -> str:
    """构造前端运行时配置 JSON 字符串."""
    base_url = _get_public_base_url(request)
    config = {
        "apiBaseUrl": f"{base_url}/api/v1",
        "appVersion": get_app_version(),
    }
    return json.dumps(config, ensure_ascii=False)


def _serve_index(request: Request) -> Response:
    """通过 Jinja2 模板渲染 index.html，注入运行时配置."""
    templates = _get_templates()
    if templates is None:
        raise HTTPException(status_code=404, detail="Console build not found")
    app_config = _build_app_config_json(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request, "app_config": app_config},
    )


def _serve_console_file(request: Request, resource_path: str | None = None) -> Response:
    console_dist_dir = _resolve_console_dist_dir()
    if console_dist_dir is None:
        raise HTTPException(status_code=404, detail="Console build not found")

    if not resource_path:
        return _serve_index(request)

    candidate = (console_dist_dir / resource_path).resolve()
    try:
        candidate.relative_to(console_dist_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")

    if candidate.is_file():
        return FileResponse(candidate)

    return _serve_index(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动事件（Lifespan）."""
    settings.ensure_directories()
    init_database()

    from paper_plane_x_backend.services.app_settings import init_app_settings_repo

    init_app_settings_repo()

    db = get_db()
    rows = db.fetchall("SELECT project_id FROM projects")
    project_ids = [row["project_id"] for row in rows]
    checked_count = get_project_file_manager().ensure_project_sandboxes(project_ids)
    if checked_count:
        logger.info("event=app.sandbox_dirs_checked count=%s", checked_count)

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


@app.get("/{resource_path:path}", include_in_schema=False)
async def console_fallback(resource_path: str, request: Request) -> Response:
    if resource_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_console_file(request, resource_path)


def run():
    import uvicorn

    uvicorn.run(
        "paper_plane_x_backend.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
        ssl_certfile=settings.api.ssl_certfile,
        ssl_keyfile=settings.api.ssl_keyfile,
    )


def debug():
    import debugpy

    debugpy.listen(("127.0.0.1", 5678))
    print("Waiting for debugger to attach on 127.0.0.1:5678")

    debugpy.wait_for_client()
    print("Debugger attached, starting the app...")
    run()


if __name__ == "__main__":
    run()
