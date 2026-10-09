# Logging Conventions

本文定义 Paper Plane X 后端日志分级与字段约定，用于统一检索、告警和问题定位。

最近审阅时间：2026-10-09。

## 1. 目标

- 日志可检索：统一使用 `event=` 事件名。
- 日志可关联：关键上下文字段固定命名（如 `paper_id`、`task_id`、`trace_id`）。
- 日志可分级：同类问题在固定级别输出。
- 日志可演进：新增模块遵循同一命名规范。

## 2. 分级约定

- `VERBOSE`（级别数值 5，低于 `DEBUG`）
  - 逐项数据输出：默认关闭，只有配置 `log.level = "VERBOSE"` 时才出现。
  - 例如：活动持久化逐记录明细 `project_activity.recorded`、LLM 流式响应的逐 chunk 摘要、逐 usage chunk。
  - 写法：`from paper_plane_x_backend.utils.logging import log_verbose`，调用 `log_verbose(logger, "event=... %s", value)`。
  - 约束：只用于诊断数据流本身；里程碑、结论和异常不使用 VERBOSE。

- `DEBUG`
  - 低成本调试信息，以及高频读路径的每次调用记录。
  - 例如：步骤开始、入参键、计数器状态、`paper.fetched`、`paper.listed`、`project_file.download`、`agent_trace.query_completed`、`cloud_mineru.task_polling` 轮询心跳。
  - 不用于业务结果和异常结论。

- `INFO`
  - 关键业务里程碑与正常状态变化。
  - 例如：任务入队、任务完成、应用启动、写操作（创建/更新/删除/上传）。
  - 约束：默认级别。循环或批量过程只输出汇总（如 `project_activity.operation_logs_migrated count=%s`），不逐行输出每条记录；逐项明细放 `DEBUG` 或 `VERBOSE`。

- `WARNING`
  - 可预期但需要关注的异常路径。
  - 例如：资源不存在、请求被业务规则阻断（如 `data_process.retry_blocked`）、可恢复失败。
  - 约束：降噪不得通过把 WARNING/ERROR 降级实现；只允许把纯读路径噪音从 INFO 移到 DEBUG/VERBOSE。

- `ERROR`
  - 明确失败且无需异常堆栈时。
  - 例如：二次失败（如失败状态回写又失败）。

- `logger.exception`（以 ERROR 级别附带堆栈，不是独立日志等级）
  - 需要保留堆栈的失败路径。
  - 例如：流程执行失败、外部依赖抛错。

### 2.1 级别配置

- `config` 中 `log.level` 接受 `VERBOSE / DEBUG / INFO / WARNING / ERROR / CRITICAL`（大小写不敏感，非法值在启动时直接报错，不再静默回退 INFO）。
- 默认 `INFO`；排障时临时用 `DEBUG`，需要逐项协议数据时用 `VERBOSE`。

## 3. 字段约定

### 3.1 通用字段

- `event`
  - 必填。
  - 事件名采用小写蛇形风格，推荐包含模块前缀。
  - 示例：`event=paper.processing_completed`。

- `error`
  - 失败类日志建议提供错误对象字符串化值。

### 3.2 业务上下文字段（按需）

- `project_id`
- `paper_id`
- `task_id`
- `trace_id`
- `agent`
- `mode`
- `step`
- `max_steps`
- `status`

### 3.3 计数和性能字段（按需）

- 计数字段统一使用 `*_count` 后缀。
  - 例如：`tool_call_count`、`referenced_image_count`。

- 时间字段统一显式单位。
  - 例如：`timeout_seconds`、`duration_ms`。

## 4. 事件命名规范

- 格式：`<domain>.<action>` 或 `<domain>.<action>_<qualifier>`
- 示例：
  - `agent.run_started`
  - `task_manager.task_failed`
  - `task_manager.tasks_recovered`
  - `data_process.retry_upload_queued`
  - `paper.manual_update_request_received`
  - `mineru.parse_http_error`

## 5. 推荐写法

```python
logger.info(
  "event=task_manager.task_submitted task_id=%s paper_id=%s",
    task_id,
    paper_id,
)

logger.exception(
  "event=agent.run_failed agent=%s mode=%s step=%s max_steps=%s",
    agent_name,
    mode,
    step,
    max_steps,
)
```

## 6. 禁止项

- 禁止无 `event=` 的自由文本日志。
- 禁止在日志模板中拼接 f-string 产生不稳定结构。
- 禁止输出敏感字段（密钥、令牌、完整用户隐私内容）。

## 7. 落地范围

本轮已对齐以下后端模块日志：

- `core/agent_runtime/*`
- `agents/*`
- `services/data_process_tasks/*`
- `services/orchestrators/*`
- `services/paper/*`
- `services/librarian/*`
- `services/pdf_parser/*`
- `api/routers/project.py`
- `api/routers/paper.py`
- `api/routers/data_process.py`
- `api/routers/librarian.py`
- `api/routers/project_files.py`
- `api/routers/pdf_parser.py`
- `api/dependencies.py`
- `main.py`
- `services/database.py`
