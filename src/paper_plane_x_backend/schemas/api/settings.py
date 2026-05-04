"""Settings API schemas."""

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field


class LLMProviderResponse(BaseModel):
    """LLM Provider 响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., description="Provider 唯一标识名")
    model: str = Field(..., description="模型名称")
    api_key: str | None = Field(default=None, description="API 密钥")
    base_url: str | None = Field(default=None, description="API 基础 URL")


class LLMProviderCreateRequest(BaseModel):
    """创建 LLM Provider 请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., min_length=1, description="Provider 唯一标识名")
    model: str = Field(..., min_length=1, description="模型名称")
    api_key: str | None = Field(default=None, description="API 密钥")
    base_url: str | None = Field(default=None, description="API 基础 URL")


class LLMProviderRenameRequest(BaseModel):
    """重命名 LLM Provider 请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., min_length=1, description="新 Provider 名称")


class LLMProviderUpdateRequest(BaseModel):
    """更新 LLM Provider 请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    model: str | None = Field(default=None, min_length=1, description="模型名称")
    api_key: str | None = Field(default=None, description="API 密钥")
    base_url: str | None = Field(default=None, description="API 基础 URL")


class AgentLLMConfigResponse(BaseModel):
    """Agent LLM 配置响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    agent_name: str = Field(..., description="Agent 名称")
    provider_name: str = Field(..., description="引用的 Provider 名称")
    temperature: float = Field(default=0.7, description="采样温度")
    max_tokens: int | None = Field(default=8192, description="最大生成 token 数")
    timeout: float = Field(default=180.0, description="请求超时时间（秒）")
    thinking_enabled: bool = Field(default=False, description="思考模式")
    reasoning_effort: str | None = Field(default=None, description="推理强度参数")
    extra_body: dict[str, Any] | None = Field(default=None, description="额外请求体参数")
    is_vlm: bool = Field(default=False, description="是否为视觉模型")

    # 解析后的有效配置预览
    effective_model: str | None = Field(default=None, description="解析后的模型名称")
    effective_base_url: str | None = Field(
        default=None, description="解析后的 API 基础 URL"
    )


class AgentLLMConfigUpdateRequest(BaseModel):
    """更新 Agent LLM 配置请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    provider_name: str = Field(..., min_length=1, description="引用的 Provider 名称")
    temperature: float | None = Field(default=None, description="覆盖采样温度")
    max_tokens: int | None = Field(default=None, description="覆盖最大生成 token 数")
    timeout: float | None = Field(default=None, description="覆盖请求超时时间（秒）")
    thinking_enabled: bool | None = Field(default=None, description="覆盖思考模式")
    reasoning_effort: str | None = Field(default=None, description="覆盖推理强度")
    extra_body: dict[str, Any] | None = Field(default=None, description="覆盖额外请求体参数")
    is_vlm: bool | None = Field(default=None, description="覆盖是否为视觉模型")


class ProviderListResponse(BaseModel):
    """Provider 列表响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[LLMProviderResponse] = Field(
        default_factory=lambda: cast(list[LLMProviderResponse], [])
    )


class AgentConfigListResponse(BaseModel):
    """Agent 配置列表响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[AgentLLMConfigResponse] = Field(
        default_factory=lambda: cast(list[AgentLLMConfigResponse], [])
    )


class MinerUConfigResponse(BaseModel):
    """MinerU 配置响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    base_url: str = Field(..., description="MinerU API 地址")
    output_dir: str = Field(..., description="MinerU 服务端输出目录参数")


class MinerUConfigUpdateRequest(BaseModel):
    """更新 MinerU 配置请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    base_url: str | None = Field(
        default=None, min_length=1, description="MinerU API 地址"
    )
    output_dir: str | None = Field(
        default=None, min_length=1, description="MinerU 服务端输出目录参数"
    )


class DataProcessConfigResponse(BaseModel):
    """Data Process 配置响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    max_retries: int = Field(default=3, description="事实核查失败最大重试次数")
    worker_count: int = Field(default=5, description="后台数据处理 worker 数量")
    shutdown_timeout: float = Field(
        default=5.0, description="后台数据处理 worker 池关闭超时时间（秒）"
    )
    task_max_seconds: float = Field(
        default=600.0, description="单个 data-process 任务最大执行时长（秒）"
    )


class DataProcessConfigUpdateRequest(BaseModel):
    """更新 Data Process 配置请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    max_retries: int | None = Field(
        default=None, ge=0, description="事实核查失败最大重试次数"
    )
    worker_count: int | None = Field(
        default=None, ge=1, description="后台数据处理 worker 数量"
    )
    shutdown_timeout: float | None = Field(
        default=None, gt=0, description="后台数据处理 worker 池关闭超时时间（秒）"
    )
    task_max_seconds: float | None = Field(
        default=None, gt=0, description="单个 data-process 任务最大执行时长（秒）"
    )


class LibrarianConfigResponse(BaseModel):
    """Librarian 配置响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    top_tags_limit: int = Field(
        default=8, ge=1, le=50, description="Global Finder 返回的热门标签数量上限"
    )


class LibrarianConfigUpdateRequest(BaseModel):
    """更新 Librarian 配置请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    top_tags_limit: int | None = Field(
        default=None, ge=1, le=50, description="Global Finder 返回的热门标签数量上限"
    )


class AppSettingsResponse(BaseModel):
    """完整应用动态配置响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    agent_llm: list[AgentLLMConfigResponse] = Field(
        default_factory=lambda: cast(list[AgentLLMConfigResponse], []),
        description="各 Agent LLM 配置",
    )
    mineru: MinerUConfigResponse = Field(..., description="MinerU 配置")
    data_process: DataProcessConfigResponse = Field(
        ..., description="Data Process 配置"
    )
    librarian: LibrarianConfigResponse = Field(..., description="Librarian 配置")
    providers: list[LLMProviderResponse] = Field(
        default_factory=lambda: cast(list[LLMProviderResponse], []),
        description="LLM Provider 列表",
    )
