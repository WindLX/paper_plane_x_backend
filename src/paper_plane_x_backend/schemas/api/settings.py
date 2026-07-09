"""Settings API schemas."""

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from paper_plane_x_backend.models.app_settings import (
    CloudPdfParserConfig,
    PandocConfig,
    PdfParserConfig,
    PdfParserType,
)


class LLMProviderResponse(BaseModel):
    """LLM Provider 响应.

    出于安全考虑，不返回 api_key：前端只能写入（覆盖后端字段），不能读取。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., description="Provider 唯一标识名")
    model: str = Field(..., description="模型名称")
    base_url: str | None = Field(default=None, description="API 基础 URL")
    has_api_key: bool = Field(
        default=False, description="后端是否已配置 api_key（不返回明文）"
    )

    @classmethod
    def from_provider(cls, provider: Any) -> "LLMProviderResponse":
        """从 LLMProvider 构建响应，剔除 api_key 明文。"""
        return cls(
            name=provider.name,
            model=provider.model,
            base_url=provider.base_url,
            has_api_key=bool(provider.api_key),
        )


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
    extra_body: dict[str, Any] | None = Field(
        default=None, description="额外请求体参数"
    )
    is_vlm: bool = Field(default=False, description="是否为视觉模型")
    short_memory_window: int = Field(
        default=99999999,
        ge=1,
        description="短期记忆窗口大小",
    )

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
    extra_body: dict[str, Any] | None = Field(
        default=None, description="覆盖额外请求体参数"
    )
    is_vlm: bool | None = Field(default=None, description="覆盖是否为视觉模型")
    short_memory_window: int | None = Field(
        default=None,
        ge=1,
        description="覆盖短期记忆窗口大小",
    )


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


# ---- PDF Parser settings ----


class LocalPdfParserConfigResponse(BaseModel):
    """本地 MinerU 解析器配置响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    base_url: str = Field(..., description="MinerU API 地址")
    output_dir: str = Field(..., description="MinerU 服务端输出目录参数")


class LocalPdfParserConfigUpdateRequest(BaseModel):
    """本地 MinerU 解析器配置更新请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    base_url: str | None = Field(
        default=None, min_length=1, description="MinerU API 地址"
    )
    output_dir: str | None = Field(
        default=None, min_length=1, description="MinerU 服务端输出目录参数"
    )


class CloudPdfParserConfigResponse(BaseModel):
    """云端 MinerU 解析器配置响应（不返回 api_key 明文）."""

    model_config = ConfigDict(strict=True, extra="forbid")

    base_url: str = Field(default="https://mineru.net", description="云端 API 基础地址")
    has_api_key: bool = Field(
        default=False, description="后端是否已配置 api_key（不返回明文）"
    )
    model_version: str = Field(
        default="pipeline", description="模型版本: pipeline / vlm / MinerU-HTML"
    )
    enable_formula: bool = Field(default=True, description="是否开启公式识别")
    enable_table: bool = Field(default=True, description="是否开启表格识别")
    is_ocr: bool = Field(default=False, description="是否启用 OCR")
    language: str = Field(default="ch", description="文档语言")

    @classmethod
    def from_config(
        cls, config: CloudPdfParserConfig
    ) -> "CloudPdfParserConfigResponse":
        return cls(
            base_url=config.base_url,
            has_api_key=bool(config.api_key),
            model_version=config.model_version,
            enable_formula=config.enable_formula,
            enable_table=config.enable_table,
            is_ocr=config.is_ocr,
            language=config.language,
        )


class CloudPdfParserConfigUpdateRequest(BaseModel):
    """云端 MinerU 解析器配置更新请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    api_key: str | None = Field(default=None, description="MinerU 云端 API Token")
    base_url: str | None = Field(
        default=None, min_length=1, description="MinerU 云端 API 基础地址"
    )
    model_version: str | None = Field(
        default=None, min_length=1, description="模型版本: pipeline / vlm / MinerU-HTML"
    )
    enable_formula: bool | None = Field(default=None, description="是否开启公式识别")
    enable_table: bool | None = Field(default=None, description="是否开启表格识别")
    is_ocr: bool | None = Field(default=None, description="是否启用 OCR")
    language: str | None = Field(default=None, min_length=1, description="文档语言")


class PdfParserConfigResponse(BaseModel):
    """PDF 解析器总配置响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    type: PdfParserType = Field(..., description="PDF 解析器类型")
    local: LocalPdfParserConfigResponse = Field(..., description="本地 MinerU 配置")
    cloud: CloudPdfParserConfigResponse = Field(..., description="云端 MinerU 配置")

    @classmethod
    def from_config(cls, config: PdfParserConfig) -> "PdfParserConfigResponse":
        return cls(
            type=config.type,
            local=LocalPdfParserConfigResponse.model_validate(
                config.local.model_dump(mode="json") if config.local else {}
            ),
            cloud=CloudPdfParserConfigResponse.from_config(
                config.cloud or CloudPdfParserConfig()
            ),
        )


class PdfParserConfigUpdateRequest(BaseModel):
    """PDF 解析器总配置更新请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    type: PdfParserType | None = Field(default=None, description="PDF 解析器类型")
    local: LocalPdfParserConfigUpdateRequest | None = Field(
        default=None, description="本地 MinerU 配置"
    )
    cloud: CloudPdfParserConfigUpdateRequest | None = Field(
        default=None, description="云端 MinerU 配置"
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


class PandocConfigResponse(BaseModel):
    """Pandoc 配置响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    pandoc_path: str | None = Field(
        default=None, description="Pandoc 可执行文件路径；为空时使用系统 PATH"
    )
    html_template: str | None = Field(
        default=None, description="Pandoc HTML 模板路径/名称；为空时使用内置默认模板"
    )
    pdf_engine: str | None = Field(
        default=None, description="Pandoc PDF engine；为空时自动选择可用引擎"
    )

    @classmethod
    def from_config(cls, config: PandocConfig) -> "PandocConfigResponse":
        return cls(
            pandoc_path=config.pandoc_path,
            html_template=config.html_template,
            pdf_engine=config.pdf_engine,
        )


class PandocConfigUpdateRequest(BaseModel):
    """更新 Pandoc 配置请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    pandoc_path: str | None = Field(
        default=None, description="Pandoc 可执行文件路径；传 null 清除自定义路径"
    )
    html_template: str | None = Field(
        default=None, description="Pandoc HTML 模板路径/名称；传 null 使用默认模板"
    )
    pdf_engine: str | None = Field(
        default=None, description="Pandoc PDF engine；传 null 自动选择可用引擎"
    )


class AppSettingsResponse(BaseModel):
    """完整应用动态配置响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    agent_llm: list[AgentLLMConfigResponse] = Field(
        default_factory=lambda: cast(list[AgentLLMConfigResponse], []),
        description="各 Agent LLM 配置",
    )
    pdf_parser: PdfParserConfigResponse = Field(..., description="PDF 解析器配置")
    data_process: DataProcessConfigResponse = Field(
        ..., description="Data Process 配置"
    )
    librarian: LibrarianConfigResponse = Field(..., description="Librarian 配置")
    pandoc: PandocConfigResponse = Field(..., description="Pandoc 配置")
    providers: list[LLMProviderResponse] = Field(
        default_factory=lambda: cast(list[LLMProviderResponse], []),
        description="LLM Provider 列表",
    )
