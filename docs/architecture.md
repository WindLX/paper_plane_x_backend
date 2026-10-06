# Backend Architecture

这份文档描述当前后端实现，面向维护 API、Agent、工具、CLI、测试和部署的开发者。

## 1. 系统目标

Paper Plane X Backend 为科研项目提供稳定的文献工作流：

1. 上传 PDF。
2. 解析 PDF 为 Markdown / 图片。
3. 运行结构化提取、理论分析与事实核查。
4. 将结果持久化到 SQLite。
5. 支持项目级文献检索、矩阵对比和单篇 deep dive。
6. 支持项目文件沙箱和论文级 paper note。
7. 通过 `ppx` CLI 与外部 `ppx-researcher` skill 把后端能力暴露给外部 Agent。

内置 Conversation、Conversation WebSocket、ResearcherAgent 和 HITL 已移除。旧库启动时会先备份数据库，再删除旧 conversation 表。

## 2. 分层结构

### 2.1 App 层

入口：

- `src/paper_plane_x_backend/main.py`

职责：

- 创建 FastAPI app。
- 注册 HTTP routers 与 Data Process WebSocket router。
- 配置 CORS。
- 托管已构建的 console 静态资源。
- 在 lifespan 中初始化目录、数据库、app settings、worker pool。

任务取消和退出的状态约束：`CANCELING` 仅表示清理尚未结束；取消完成后任务为 `CANCELED`，文献为可重试的 `FAILED`。任务存储持久化取消/失败状态时，仅释放没有其他活跃任务的文献。worker 关闭后不继续消费积压队列，未执行任务保留并在重启时恢复；重启不会恢复用户已经请求取消的任务。历史状态修复采用显式备份命令，见 [退出、取消与旧状态修复](workflow_quickstart.md#退出取消与旧状态修复)。

### 2.2 API 层

目录：

- `src/paper_plane_x_backend/api/routers/`
- `src/paper_plane_x_backend/api/dependencies.py`
- `src/paper_plane_x_backend/schemas/api/`

职责：

- HTTP / WebSocket 入参校验。
- 响应模型封装。
- 领域错误映射为 HTTP 错误。
- 将业务编排委托给 orchestrator / service / agent。

当前路由分组：

| Router            | Prefix                                | 说明                                                              |
| ----------------- | ------------------------------------- | ----------------------------------------------------------------- |
| `paper`           | `/api/v1/papers`                      | 论文上传、详情、更新、删除、重处理、agent note                    |
| `project`         | `/api/v1/projects`                    | 项目 CRUD、agent summary、导出、论文关联、项目搜索                |
| `project_files`   | `/api/v1/projects/{project_id}/files` | 项目文件沙箱 list/read/write/find/patch/export                    |
| `librarian`       | `/api/v1/librarian`                   | search、matrix、deep-dive、global-finder、query-builder           |
| `data_process`    | `/api/v1/data-process`                | 任务列表、详情、取消、重试、删除                                  |
| `data_process_ws` | `/api/v1/ws/data-process`             | Data Process 任务实时事件                                         |
| `agent_traces`    | `/api/v1/agent-traces`                | trace 查询、列表、删除                                            |
| `settings`        | `/api/v1/settings`                    | LLM provider、Agent LLM、PDF Parser、Data Process、Librarian 配置 |
| `pdf_parser`      | `/api/v1/pdf-parser`                  | 单文件 PDF 解析为 Markdown                                        |

### 2.3 Orchestrator 层

目录：

- `src/paper_plane_x_backend/services/orchestrators/`

职责：

- 跨 repository、task manager、parser、processor 组合流程。
- 对 API 层提供稳定业务边界。
- 将 repository 错误映射成 domain error。

主要 orchestrator：

- `ProjectOrchestrator`
- `PaperOrchestrator`
- `DataProcessOrchestrator`
- `LibrarianOrchestrator`

### 2.4 Service / Repository 层

目录：

- `src/paper_plane_x_backend/services/database.py`
- `src/paper_plane_x_backend/services/paper/`
- `src/paper_plane_x_backend/services/project/`
- `src/paper_plane_x_backend/services/data_process_tasks/`
- `src/paper_plane_x_backend/services/librarian/`
- `src/paper_plane_x_backend/services/app_settings/`
- `src/paper_plane_x_backend/services/pdf_parser/`

职责：

- SQLite 初始化与轻量迁移。
- Paper / Project / Trace 数据访问。
- Data Process 任务持久化与 worker 生命周期。
- Librarian 字段读取、搜索和矩阵组装。
- PDF Parser 本地/云端配置与解析适配。

### 2.5 Agent Runtime 层

目录：

- `src/paper_plane_x_backend/core/agent_runtime/`
- `src/paper_plane_x_backend/agents/`
- `src/paper_plane_x_backend/tools/`

职责：

- LLM 请求封装。
- OpenAI-compatible tool-call 循环。
- ToolRegistry、`@tool` 装饰器、context injection。
- Memory 管理。
- Structured output 校验。
- Agent trace 落库。

`Tool.execute` 的隐藏上下文参数使用 `runtime_context` 注入，例如 `project_id`、caller 信息。不要使用旧的 `context=` 形态。

当前后端 Agent：

- `DataProcessorAgentGroup`
- `QueryBuilderAgent`
- `GlobalFinderAgent`
- `DeepDiverAgent`

## 3. Data Process 主链路

入口：

- `POST /api/v1/papers`
- `POST /api/v1/papers/{paper_id}/reprocess`
- `PATCH /api/v1/papers/{paper_id}` 用于人工回填或修正字段

流程：

1. 接收 PDF 上传。
2. 计算文件 hash，创建或复用 paper 记录。
3. 创建 data-process task 并入队。
4. worker 执行 `PaperParser`，生成 Markdown 和图片。
5. `DataProcessorAgentGroup` 并行运行 Extraction / Analysis。
6. 两个分支分别执行 Fact Check。
7. `PaperProcessor` 写回 `papers` 表，更新状态和 trace ids。

关键状态：

- `extraction_status`
- `extraction_fact_check_status`
- `analysis_fact_check_status`

完全可用于搜索的论文通常满足：

- `extraction_status` 为 `COMPLETED` 或 `HUMAN_COMPLETED`
- `extraction_fact_check_status` 为 `PASSED` 或 `HUMAN_PASSED`
- `analysis_fact_check_status` 为 `PASSED` 或 `HUMAN_PASSED`

## 4. Librarian

入口：

- `POST /api/v1/librarian/search`
- `POST /api/v1/librarian/matrix`
- `POST /api/v1/librarian/deep-dive`
- `POST /api/v1/librarian/global-finder`
- `POST /api/v1/librarian/global-finder/agent-summary`
- `POST /api/v1/librarian/query-builder`
- `POST /api/v1/projects/{project_id}/search`

核心数据来自 `papers` 表中的：

- `md_content`
- `quick_scan`
- `synthesis_data`
- `analysis_report`
- 论文元数据字段

Librarian 使用 DSL 查询和 field_paths 做精确提取。详见 [librarian.md](./librarian.md)。

## 5. `ppx` CLI 与外部 Skill

`ppx` CLI 位于兄弟包 `../../paper_plane_x_cli`。

特点：

- 只通过 HTTP 调 FastAPI。
- 不 import backend tools，不读写 DB。
- 输出 JSON，方便 Codex / Claude Code / shell 脚本解析。
- context 优先级：命令参数 > 环境变量 > 本地 context > 全局 context > 默认 base URL。

常用：

```bash
ppx context set --base-url http://127.0.0.1:8000/api/v1 --project-id prj_x
ppx project global-finder
ppx librarian search --query-expr "(meta.title CONTAINS transformer)"
ppx files list --dir /
```

外部 Agent skill：

- `../../paper_plane_x_cli/skills/ppx-researcher/SKILL.md`
- `../../paper_plane_x_cli/skills/ppx-researcher/references/tool-guide.md`
- `../../paper_plane_x_cli/skills/ppx-pdf-to-markdown/SKILL.md`

这些 skill 使用 HTTP CLI 调用后端能力。

## 6. 数据模型与存储

主存储：SQLite。

关键表：

- `projects`
- `papers`
- `paper_projects`
- `data_process_tasks`
- `agent_traces`
- `papers_fts`

旧表：

- `conversations`
- `conversation_messages`

如果旧数据库存在这些表，`init_tables()` 会先调用数据库备份逻辑，再删除旧 conversation 表。

`papers` 表保存：

- 论文元数据
- 原始 PDF 路径和 hash
- Markdown 与图片路径
- `quick_scan`
- `synthesis_data`
- `analysis_report`
- fact check 状态与结果
- retry 计数
- `agent_note`

结构化结果采用 JSON blob，是因为字段仍在演化，且 SQLite `json_extract` / FTS5 已能支撑当前搜索和矩阵读取。

## 7. 配置与运行时文件

后端有两套配置，不要混用：

**ServerConfig（启动只读）**

由 `pydantic-settings` 管理，决定服务怎么启动：监听地址、端口、日志路径、数据目录、CORS 等。

来源优先级（高到低）：

1. 初始化参数
2. 系统环境变量（`PPX_*`）
3. `.env` 文件
4. `PPX_CONFIG_FILE` 指向的 TOML 文件（默认 `config/default.toml`）

示例字段：`PPX_API__PORT`, `PPX_DATA_DIR`, `PPX_LOG__LEVEL`。

**AppSettings（运行时动态）**

决定 Agent 调谁、用什么模型、PDF Parser 在哪。
通过 Settings API 或 `data/app_settings.toml` 读写，服务启动后随时可改。

包含：LLM Provider 列表、Agent LLM 绑定、PDF Parser、Data Process 参数、Librarian 参数。

首次启动后必须先配 Provider 和 Agent LLM，否则所有需要 LLM 的操作都会失败。

常见运行时文件：

- `data/app.db`
- `data/papers/`
- `data/project_files/`
- `data/backups/`
- `data/logs/`
- `data/console/`

后端 console 静态资源查找顺序：

1. `settings.api.console_dist_dir`
2. `../paper_plane_x_frontend/dist`

## 8. 开发维护原则

- API 层保持薄：校验、依赖注入、HTTP 映射。
- 业务组合放 orchestrator。
- 数据访问放 repository。
- Agent 工具说明要同步到外部 skill。
- 新 API 必须补 integration test。
- 修改 tool context 语义时必须跑 agent runtime tests。
- 文档里不保留已经删除的路由或旧设计草稿。
