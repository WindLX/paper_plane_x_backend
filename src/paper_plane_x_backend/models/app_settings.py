"""应用动态配置模型.

这些配置可在运行时通过 API/UI 修改，持久化到 data/app_settings.toml。
与 ServerConfig（启动只读）分离。
"""

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

# 预定义的 Agent 名称（与 AgentLLMConfigs 字段一一对应）
AGENT_NAMES: tuple[str, ...] = (
    "extraction",
    "analysis",
    "fact_check",
    "deep_diver",
    "query_builder",
    "global_finder",
    "researcher",
    "subagent",
)


class LLMConfig(BaseModel):
    """LLM 配置模型.

    支持为不同 Agent 配置不同的 LLM 参数。
    """

    model: str = Field(default="gpt-4o", description="模型名称")
    api_key: str | None = Field(default=None, description="API 密钥")
    base_url: str | None = Field(
        default=None,
        description="API 基础 URL (VLLM: http://localhost:8000/v1)",
    )
    temperature: float = Field(default=0.7, description="采样温度")
    max_tokens: int | None = Field(default=8192, description="最大生成 token 数")
    timeout: float = Field(default=180.0, description="请求超时时间（秒）")
    custom_headers: dict[str, str] | None = Field(
        default=None, description="自定义 HTTP 请求头"
    )
    thinking_enabled: bool = Field(
        default=False,
        description="是否启用模型思考模式（由 LLMClient 映射到兼容参数）",
    )
    reasoning_effort: str | None = Field(
        default=None,
        description="推理强度参数（如 OpenAI reasoning_effort，按模型能力生效）",
    )
    extra_body: dict[str, Any] | None = Field(
        default=None,
        description="额外请求体参数，用于透传厂商私有扩展",
    )
    is_vlm: bool = Field(
        default=False,
        description="是否为视觉模型（启用多模态消息处理）",
    )


class AgentLLMConfigEntry(BaseModel):
    """Agent LLM 配置条目.

    通过引用 Provider 名称 + 可选覆盖项来配置 Agent 的 LLM 参数。
    """

    model_config = ConfigDict(extra="ignore")

    provider_name: str = Field(default="default", description="引用的 Provider 名称")
    temperature: float = Field(default=0.7, description="采样温度")
    max_tokens: int | None = Field(default=8192, description="最大生成 token 数")
    timeout: float = Field(default=180.0, description="请求超时时间（秒）")
    thinking_enabled: bool = Field(default=False, description="思考模式开关")
    reasoning_effort: str | None = Field(default=None, description="推理强度参数")
    extra_body: dict[str, Any] | None = Field(
        default=None, description="额外请求体参数"
    )
    is_vlm: bool = Field(default=False, description="是否为视觉模型")


class AgentLLMConfigs(BaseModel):
    """各 Agent 的 LLM 配置.

    每个 Agent 引用一个 Provider 名称，并可选覆盖部分参数。
    未配置则使用全局默认 LLM 配置。
    """

    model_config = ConfigDict(extra="ignore")

    # Data Process Agents
    extraction: AgentLLMConfigEntry | None = Field(
        default=None, description="ExtractionAgent 配置"
    )
    analysis: AgentLLMConfigEntry | None = Field(
        default=None, description="AnalysisAgent 配置"
    )
    fact_check: AgentLLMConfigEntry | None = Field(
        default=None, description="FactCheckAgent 配置"
    )

    # Librarian Agents
    deep_diver: AgentLLMConfigEntry | None = Field(
        default=None, description="DeepDiverAgent 配置"
    )
    query_builder: AgentLLMConfigEntry | None = Field(
        default=None, description="QueryBuilderAgent 配置"
    )
    global_finder: AgentLLMConfigEntry | None = Field(
        default=None, description="GlobalFinderAgent 配置"
    )

    # Conversation Agents
    researcher: AgentLLMConfigEntry | None = Field(
        default=None, description="ResearcherAgent 配置"
    )
    subagent: AgentLLMConfigEntry | None = Field(
        default=None, description="SubAgent 配置"
    )


class LLMProvider(BaseModel):
    """LLM Provider 配置模型.

    用于在 Provider 池中定义一个可复用的 LLM 服务端点。
    仅保留连接相关参数，其他参数在 agent_llm 中配置。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., min_length=1, description="Provider 唯一标识名")
    model: str = Field(..., min_length=1, description="模型名称")
    api_key: str | None = Field(default=None, description="API 密钥")
    base_url: str | None = Field(
        default=None,
        description="API 基础 URL (VLLM: http://localhost:8000/v1)",
    )


class MinerUConfig(BaseModel):
    """MinerU 配置."""

    base_url: str = Field(
        default="http://localhost:7860", description="MinerU API 地址"
    )
    output_dir: Path = Field(
        default=Path("./data/papers"), description="MinerU 服务端输出目录参数"
    )


class DataProcessConfig(BaseModel):
    """Data Process 运行时配置."""

    max_retries: int = Field(default=3, description="事实核查失败最大重试次数")
    worker_count: int = Field(default=5, description="后台数据处理 worker 数量")
    shutdown_timeout: float = Field(
        default=5.0,
        description="后台数据处理 worker 池关闭超时时间（秒）",
    )
    task_max_seconds: float = Field(
        default=600.0,
        description="单个 data-process 任务最大执行时长（秒）",
    )


class LibrarianConfig(BaseModel):
    """Librarian 运行时配置。"""

    top_tags_limit: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Global Finder 返回的热门标签数量上限",
    )


class AppSettings(BaseModel):
    """应用动态配置.

    可在运行时通过 API 修改，持久化到 TOML 文件。
    """

    model_config = ConfigDict(extra="ignore")

    # LLM Provider 池
    providers: list[LLMProvider] = Field(
        default_factory=lambda: cast(list[LLMProvider], []),
        description="LLM Provider 列表",
    )

    # 各 Agent 独立 LLM 配置（不再继承全局默认配置，每个 Agent 必须手动配置）
    agent_llm: AgentLLMConfigs = Field(default_factory=AgentLLMConfigs)

    # MinerU 配置
    mineru: MinerUConfig = Field(default_factory=MinerUConfig)

    # Data Process 配置
    data_process: DataProcessConfig = Field(default_factory=DataProcessConfig)

    # Librarian 配置
    librarian: LibrarianConfig = Field(default_factory=LibrarianConfig)
