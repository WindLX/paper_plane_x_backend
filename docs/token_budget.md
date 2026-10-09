# Agent 请求 Token 总预算

六个 Agent（extraction、analysis、fact_check、deep_diver、query_builder、global_finder）统一使用 `max_total_tokens`，默认 **240000**。它表示一次模型请求中系统提示、历史、当前输入、工具定义、结构化输出 schema 与本次生成的总预算，不是多轮运行的累计计费上限。

后端根据请求中的实际模型名调用 LiteLLM 自动估算输入量，无需配置 tokenizer。普通、结构化与流式调用共用同一请求构造入口；每次调用重新计数，包括工具结果和校验反馈增加后的输入。输出预算包含由对应模型协议计入生成量的推理 Token。

```text
有效总预算 = min(max_total_tokens, 模型上下文上限)
生成上限 = min(有效总预算 - 估算输入量 - 4096, 模型最大生成量)
```

模型信息来自 LiteLLM 的本地模型注册表。Provider 可选的 `context_window_tokens`、`max_output_tokens` 用于声明自定义网关的实际能力，并优先于注册表；这两个字段可在 Settings 的 Provider 高级设置中填写或清空。未知模型未声明限制时，使用已配置的总预算作为本地上限，日志中的 `context_limit=None` 明确表示没有识别到服务端窗口。

例如总预算 240000、估算输入 76261、模型上下文 262144 时，剩余生成空间为 **159643**；若模型还有更小的生成限制，则继续取较小值。总预算不会强制用满，也不能扩展模型本身的上下文。

计数是估算，额外预留 4096 Token 处理 tokenizer、消息模板及网关封装差异。多模态图像使用 LiteLLM 默认图像计数，避免预算阶段下载外部图片。自定义模型和图像估算不等价于服务端的精确计数；实际 usage 继续由服务端返回。

输入已经占满预算时，在调用模型前报告错误，包含估算输入量、有效总预算和安全余量。不自动裁剪或压缩历史，不截断论文，不增加分块汇总，也不在上下文错误后自动重试。

## 配置与旧字段清理

```toml
[agent_llm.global_finder]
provider_name = "default"
max_total_tokens = 240000
```

设置 API 示例：

```bash
curl -X PUT http://127.0.0.1:8000/api/v1/settings/agent_llm/global_finder \
  -H 'Content-Type: application/json' \
  -d '{"provider_name":"default","max_total_tokens":240000}'
```

旧的用户配置字段 `max_tokens` 已删除，不提供兼容映射。升级时从 `data/app_settings.toml` 各 `[agent_llm.<name>]` 节移除旧字段，并写入 `max_total_tokens = 240000`；不要把原输出上限直接当成总预算。带旧字段的设置请求返回 422，旧 Agent TOML 字段会导致配置校验失败。模型请求协议仍使用后端计算出的 `max_tokens`，用户不能通过 `extra_body` 中的输出限制绕过预算。

## 验证

运行 `just test tests/unit/test_llm_token_budget.py tests/integration/test_settings_api.py`，覆盖长输入、工具与 schema 计数、流式请求、模型限制、六个默认预算、旧字段拒绝和 Provider 能力清空。运行 `just pre-commit` 完成完整检查。
