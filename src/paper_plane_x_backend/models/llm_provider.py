"""LLM Provider 数据模型."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LLMProvider(BaseModel):
    """LLM Provider 配置模型.

    用于在 Provider 池中定义一个可复用的 LLM 服务端点。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., min_length=1, description="Provider 唯一标识名")
    model: str = Field(..., min_length=1, description="模型名称")
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
