"""Settings 配置管理路由."""

import logging
from typing import NoReturn

from fastapi import APIRouter, HTTPException, status

from paper_plane_x_backend.models.app_settings import AGENT_NAMES, AgentLLMConfigEntry
from paper_plane_x_backend.schemas.api import (
    AgentConfigListResponse,
    AgentLLMConfigResponse,
    AgentLLMConfigUpdateRequest,
    AppSettingsResponse,
    DataProcessConfigResponse,
    DataProcessConfigUpdateRequest,
    GlobalLLMConfigResponse,
    GlobalLLMConfigUpdateRequest,
    LibrarianConfigResponse,
    LibrarianConfigUpdateRequest,
    LLMProviderCreateRequest,
    LLMProviderResponse,
    LLMProviderUpdateRequest,
    MinerUConfigResponse,
    MinerUConfigUpdateRequest,
    ProviderListResponse,
)
from paper_plane_x_backend.services.app_settings import (
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
        "immutable_name": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "invalid_agent": status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    items = [
        LLMProviderResponse.model_validate(p.model_dump(mode="json"))
        for p in repo.list_providers()
    ]
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
    return LLMProviderResponse.model_validate(provider.model_dump(mode="json"))


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
    return LLMProviderResponse.model_validate(provider.model_dump(mode="json"))


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
    return LLMProviderResponse.model_validate(updated.model_dump(mode="json"))


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
    items = [
        AgentLLMConfigResponse.model_validate(build_agent_config_response(name))
        for name in AGENT_NAMES
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
        build_agent_config_response(agent_name)
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Provider '{request.provider_name}' not found",
        )

    entry = AgentLLMConfigEntry.model_validate(request.model_dump())
    try:
        _repo().update_agent_llm(
            agent_name, entry.model_dump(mode="json", exclude_none=True)
        )
    except AppSettingsRepositoryError as exc:
        _raise_as_http(exc)

    return AgentLLMConfigResponse.model_validate(
        build_agent_config_response(agent_name)
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
        llm=GlobalLLMConfigResponse.model_validate(
            app_settings.llm.model_dump(mode="json")
        ),
        agent_llm=[
            AgentLLMConfigResponse.model_validate(build_agent_config_response(name))
            for name in AGENT_NAMES
        ],
        mineru=MinerUConfigResponse.model_validate(
            app_settings.mineru.model_dump(mode="json")
        ),
        data_process=DataProcessConfigResponse.model_validate(
            app_settings.data_process.model_dump(mode="json")
        ),
        librarian=LibrarianConfigResponse.model_validate(
            app_settings.librarian.model_dump(mode="json")
        ),
        providers=[
            LLMProviderResponse.model_validate(p.model_dump(mode="json"))
            for p in app_settings.providers
        ],
    )


@router.get(
    "/llm",
    response_model=GlobalLLMConfigResponse,
    summary="获取全局 LLM 配置",
)
def get_global_llm_config() -> GlobalLLMConfigResponse:
    logger.debug("event=settings.global_llm_get_request_received")
    app_settings = _repo().get()
    return GlobalLLMConfigResponse.model_validate(
        app_settings.llm.model_dump(mode="json")
    )


@router.put(
    "/llm",
    response_model=GlobalLLMConfigResponse,
    summary="更新全局 LLM 配置",
)
def update_global_llm_config(
    request: GlobalLLMConfigUpdateRequest,
) -> GlobalLLMConfigResponse:
    logger.info("event=settings.global_llm_update_request_received")
    updated = _repo().update_llm(request.model_dump(mode="json", exclude_none=True))
    return GlobalLLMConfigResponse.model_validate(updated.llm.model_dump(mode="json"))


@router.get(
    "/mineru",
    response_model=MinerUConfigResponse,
    summary="获取 MinerU 配置",
)
def get_mineru_config() -> MinerUConfigResponse:
    logger.debug("event=settings.mineru_get_request_received")
    app_settings = _repo().get()
    return MinerUConfigResponse.model_validate(
        app_settings.mineru.model_dump(mode="json")
    )


@router.put(
    "/mineru",
    response_model=MinerUConfigResponse,
    summary="更新 MinerU 配置",
)
def update_mineru_config(
    request: MinerUConfigUpdateRequest,
) -> MinerUConfigResponse:
    logger.info("event=settings.mineru_update_request_received")
    updated = _repo().update_mineru(request.model_dump(mode="json", exclude_none=True))
    return MinerUConfigResponse.model_validate(updated.mineru.model_dump(mode="json"))


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
