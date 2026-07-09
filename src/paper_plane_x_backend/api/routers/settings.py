"""Settings 配置管理路由."""

import logging
from typing import Any, NoReturn, cast

from fastapi import APIRouter, HTTPException, status

from paper_plane_x_backend.models.app_settings import (
    AGENT_NAMES,
    AgentLLMConfigEntry,
)
from paper_plane_x_backend.schemas.api import (
    AgentConfigListResponse,
    AgentLLMConfigResponse,
    AgentLLMConfigUpdateRequest,
    AppSettingsResponse,
    CloudPdfParserConfigUpdateRequest,
    DataProcessConfigResponse,
    DataProcessConfigUpdateRequest,
    LibrarianConfigResponse,
    LibrarianConfigUpdateRequest,
    LLMProviderCreateRequest,
    LLMProviderRenameRequest,
    LLMProviderResponse,
    LLMProviderUpdateRequest,
    LocalPdfParserConfigUpdateRequest,
    PandocConfigResponse,
    PandocConfigUpdateRequest,
    PdfParserConfigResponse,
    ProviderListResponse,
)
from paper_plane_x_backend.services.app_settings import (
    AgentConfigResponsePayload,
    AppSettingsRepository,
    AppSettingsRepositoryError,
    build_agent_config_response,
    get_app_settings_repo,
)

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger(__name__)


def _repo() -> AppSettingsRepository:
    return get_app_settings_repo()


def _raise_as_http(exc: AppSettingsRepositoryError) -> NoReturn:
    status_map = {
        "not_found": status.HTTP_404_NOT_FOUND,
        "already_exists": status.HTTP_409_CONFLICT,
        "immutable_name": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_agent": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_toml": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "io_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "invalid_data": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }
    code = status_map.get(exc.error_code, status.HTTP_400_BAD_REQUEST)
    logger.warning(
        "event=settings.domain_error status=%s code=%s detail=%s",
        code,
        exc.error_code,
        exc.message,
    )
    raise HTTPException(status_code=code, detail=exc.message)


# ---- Providers ----


@router.get(
    "/providers",
    response_model=ProviderListResponse,
    summary="列出所有 LLM Provider",
)
def list_providers() -> ProviderListResponse:
    logger.debug("event=settings.providers_list_request_received")
    repo = _repo()
    items = [LLMProviderResponse.from_provider(p) for p in repo.list_providers()]
    return ProviderListResponse(items=items)


@router.get(
    "/providers/{name}",
    response_model=LLMProviderResponse,
    summary="获取单个 LLM Provider",
    responses={404: {"description": "Provider 不存在"}},
)
def get_provider(name: str) -> LLMProviderResponse:
    logger.debug("event=settings.provider_get_request_received name=%s", name)
    repo = _repo()
    provider = repo.get_provider(name)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{name}' not found",
        )
    return LLMProviderResponse.from_provider(provider)


@router.post(
    "/providers",
    response_model=LLMProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建 LLM Provider",
    responses={409: {"description": "Provider 已存在"}},
)
def create_provider(
    request: LLMProviderCreateRequest,
) -> LLMProviderResponse:
    logger.info("event=settings.provider_create_request_received name=%s", request.name)
    from paper_plane_x_backend.models.app_settings import LLMProvider

    provider = LLMProvider.model_validate(request.model_dump())
    try:
        _repo().create_provider(provider)
    except AppSettingsRepositoryError as exc:
        _raise_as_http(exc)
    return LLMProviderResponse.from_provider(provider)


@router.put(
    "/providers/{name}",
    response_model=LLMProviderResponse,
    summary="更新 LLM Provider",
    responses={404: {"description": "Provider 不存在"}},
)
def update_provider(
    name: str,
    request: LLMProviderUpdateRequest,
) -> LLMProviderResponse:
    logger.info("event=settings.provider_update_request_received name=%s", name)
    try:
        updated = _repo().update_provider(
            name, request.model_dump(mode="json", exclude_none=True)
        )
    except AppSettingsRepositoryError as exc:
        _raise_as_http(exc)
    return LLMProviderResponse.from_provider(updated)


@router.put(
    "/providers/{name}/rename",
    response_model=LLMProviderResponse,
    summary="重命名 LLM Provider",
    responses={
        404: {"description": "Provider 不存在"},
        409: {"description": "新名称已存在"},
    },
)
def rename_provider(
    name: str,
    request: LLMProviderRenameRequest,
) -> LLMProviderResponse:
    logger.info(
        "event=settings.provider_rename_request_received old=%s new=%s",
        name,
        request.name,
    )
    try:
        renamed = _repo().rename_provider(name, request.name)
    except AppSettingsRepositoryError as exc:
        _raise_as_http(exc)
    return LLMProviderResponse.from_provider(renamed)


@router.delete(
    "/providers/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 LLM Provider",
    responses={404: {"description": "Provider 不存在"}},
)
def delete_provider(name: str) -> None:
    logger.info("event=settings.provider_delete_request_received name=%s", name)
    try:
        _repo().delete_provider(name)
    except AppSettingsRepositoryError as exc:
        _raise_as_http(exc)


# ---- Agent LLM ----


@router.get(
    "/agent_llm",
    response_model=AgentConfigListResponse,
    summary="列出所有 Agent 的 LLM 配置",
)
def list_agent_llm() -> AgentConfigListResponse:
    logger.debug("event=settings.agent_llm_list_request_received")
    payloads: list[AgentConfigResponsePayload] = [
        build_agent_config_response(name) for name in AGENT_NAMES
    ]
    items = [
        AgentLLMConfigResponse.model_validate(cast(dict[str, Any], payload))
        for payload in payloads
    ]
    return AgentConfigListResponse(items=items)


@router.get(
    "/agent_llm/{agent_name}",
    response_model=AgentLLMConfigResponse,
    summary="获取单个 Agent 的 LLM 配置",
    responses={404: {"description": "Agent 不存在"}},
)
def get_agent_llm(agent_name: str) -> AgentLLMConfigResponse:
    logger.debug(
        "event=settings.agent_llm_get_request_received agent_name=%s", agent_name
    )
    if agent_name not in AGENT_NAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found",
        )
    return AgentLLMConfigResponse.model_validate(
        cast(dict[str, Any], build_agent_config_response(agent_name))
    )


@router.put(
    "/agent_llm/{agent_name}",
    response_model=AgentLLMConfigResponse,
    summary="更新 Agent 的 LLM 配置",
    responses={
        404: {"description": "Agent 不存在"},
        422: {"description": "Provider 不存在"},
    },
)
def update_agent_llm(
    agent_name: str,
    request: AgentLLMConfigUpdateRequest,
) -> AgentLLMConfigResponse:
    logger.info(
        "event=settings.agent_llm_update_request_received agent_name=%s provider=%s",
        agent_name,
        request.provider_name,
    )
    if agent_name not in AGENT_NAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found",
        )

    # 校验 provider 是否存在
    provider = _repo().get_provider(request.provider_name)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Provider '{request.provider_name}' not found",
        )

    entry = AgentLLMConfigEntry.model_validate(request.model_dump(exclude_none=True))
    try:
        _repo().update_agent_llm(
            agent_name, entry.model_dump(mode="json", exclude_none=True)
        )
    except AppSettingsRepositoryError as exc:
        _raise_as_http(exc)

    return AgentLLMConfigResponse.model_validate(
        cast(dict[str, Any], build_agent_config_response(agent_name))
    )


# ---- Settings sections ----


@router.get(
    "",
    response_model=AppSettingsResponse,
    summary="获取完整应用动态配置",
)
def get_app_settings() -> AppSettingsResponse:
    logger.debug("event=settings.app_settings_get_request_received")
    app_settings = _repo().get()
    return AppSettingsResponse(
        agent_llm=[
            AgentLLMConfigResponse.model_validate(build_agent_config_response(name))
            for name in AGENT_NAMES
        ],
        pdf_parser=PdfParserConfigResponse.from_config(app_settings.pdf_parser),
        data_process=DataProcessConfigResponse.model_validate(
            app_settings.data_process.model_dump(mode="json")
        ),
        librarian=LibrarianConfigResponse.model_validate(
            app_settings.librarian.model_dump(mode="json")
        ),
        pandoc=PandocConfigResponse.from_config(app_settings.pandoc),
        providers=[
            LLMProviderResponse.from_provider(p) for p in app_settings.providers
        ],
    )


# ---- PDF Parser ----


@router.get(
    "/pdf-parser",
    response_model=PdfParserConfigResponse,
    summary="获取 PDF 解析器配置",
)
def get_pdf_parser_config() -> PdfParserConfigResponse:
    logger.debug("event=settings.pdf_parser_get_request_received")
    app_settings = _repo().get()
    return PdfParserConfigResponse.from_config(app_settings.pdf_parser)


@router.put(
    "/pdf-parser/local",
    response_model=PdfParserConfigResponse,
    summary="更新本地 PDF 解析器配置",
)
def update_local_pdf_parser_config(
    request: LocalPdfParserConfigUpdateRequest,
) -> PdfParserConfigResponse:
    logger.info("event=settings.pdf_parser_local_update_request_received")
    try:
        updated = _repo().update_pdf_parser(
            {
                "type": "local_mineru",
                "local": request.model_dump(mode="json", exclude_none=True),
            }
        )
    except AppSettingsRepositoryError as exc:
        _raise_as_http(exc)
    return PdfParserConfigResponse.from_config(updated.pdf_parser)


@router.put(
    "/pdf-parser/cloud",
    response_model=PdfParserConfigResponse,
    summary="更新云端 PDF 解析器配置",
)
def update_cloud_pdf_parser_config(
    request: CloudPdfParserConfigUpdateRequest,
) -> PdfParserConfigResponse:
    logger.info("event=settings.pdf_parser_cloud_update_request_received")
    try:
        updated = _repo().update_pdf_parser(
            {
                "type": "cloud_mineru",
                "cloud": request.model_dump(mode="json", exclude_none=True),
            }
        )
    except AppSettingsRepositoryError as exc:
        _raise_as_http(exc)
    return PdfParserConfigResponse.from_config(updated.pdf_parser)


# ---- Data Process / Librarian ----


@router.get(
    "/data-process",
    response_model=DataProcessConfigResponse,
    summary="获取 Data Process 配置",
)
def get_data_process_config() -> DataProcessConfigResponse:
    logger.debug("event=settings.data_process_get_request_received")
    app_settings = _repo().get()
    return DataProcessConfigResponse.model_validate(
        app_settings.data_process.model_dump(mode="json")
    )


@router.put(
    "/data-process",
    response_model=DataProcessConfigResponse,
    summary="更新 Data Process 配置",
)
def update_data_process_config(
    request: DataProcessConfigUpdateRequest,
) -> DataProcessConfigResponse:
    logger.info("event=settings.data_process_update_request_received")
    updated = _repo().update_data_process(
        request.model_dump(mode="json", exclude_none=True)
    )
    return DataProcessConfigResponse.model_validate(
        updated.data_process.model_dump(mode="json")
    )


@router.get(
    "/librarian",
    response_model=LibrarianConfigResponse,
    summary="获取 Librarian 配置",
)
def get_librarian_config() -> LibrarianConfigResponse:
    logger.debug("event=settings.librarian_get_request_received")
    app_settings = _repo().get()
    return LibrarianConfigResponse.model_validate(
        app_settings.librarian.model_dump(mode="json")
    )


@router.put(
    "/librarian",
    response_model=LibrarianConfigResponse,
    summary="更新 Librarian 配置",
)
def update_librarian_config(
    request: LibrarianConfigUpdateRequest,
) -> LibrarianConfigResponse:
    logger.info("event=settings.librarian_update_request_received")
    updated = _repo().update_librarian(
        request.model_dump(mode="json", exclude_none=True)
    )
    return LibrarianConfigResponse.model_validate(
        updated.librarian.model_dump(mode="json")
    )


# ---- Pandoc ----


@router.get(
    "/pandoc",
    response_model=PandocConfigResponse,
    summary="获取 Pandoc 配置",
)
def get_pandoc_config() -> PandocConfigResponse:
    logger.debug("event=settings.pandoc_get_request_received")
    app_settings = _repo().get()
    return PandocConfigResponse.from_config(app_settings.pandoc)


@router.put(
    "/pandoc",
    response_model=PandocConfigResponse,
    summary="更新 Pandoc 配置",
)
def update_pandoc_config(
    request: PandocConfigUpdateRequest,
) -> PandocConfigResponse:
    logger.info("event=settings.pandoc_update_request_received")
    values: dict[str, str | None] = {}
    for field in ("pandoc_path", "html_template", "pdf_engine"):
        if field not in request.model_fields_set:
            continue
        raw = getattr(request, field)
        values[field] = raw.strip() if raw else None
    updated = _repo().update_pandoc(values)
    return PandocConfigResponse.from_config(updated.pandoc)
