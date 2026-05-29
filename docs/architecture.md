# Backend Architecture

这份文档描述 **当前实现** 的后端结构。它面向要维护 API、Agent、工具、CLI、测试和部署的开发者。

## 1. 系统目标

Paper Plane X Backend 的目标是为科研项目提供一条稳定的文献工作流：

1. 上传 PDF。
2. 解析 PDF 为 Markdown / 图片。
3. 运行结构化提取、理论分析与事实核查。
4. 将结果持久化到 SQLite。
5. 支持项目级文献检索、矩阵对比和单篇 deep dive。
6. 支持 ResearcherAgent 项目对话、项目文件沙箱和论文笔记。
7. 通过 `ppx` CLI 与 Researcher skill 把工具能力暴露给外部 agent。

## 2. 分层结构

### 2.1 App 层

入口：

- `src/paper_plane_x_backend/main.py`

职责：

- 创建 FastAPI app。
- 注册 HTTP routers 与 WebSocket routers。
- 配置 CORS。
- 托管已构建的 console 静态资源。
- 在 lifespan 中初始化目录、数据库、app settings、worker pool。

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

| Router            | Prefix                                       | 说明                                                          |
| ----------------- | -------------------------------------------- | ------------------------------------------------------------- |
| `paper`           | `/api/v1/papers`                             | 论文上传、详情、更新、删除、重处理、agent note                |
| `project`         | `/api/v1/projects`                           | 项目 CRUD、agent summary、导出、论文关联、项目搜索            |
| `project_files`   | `/api/v1/projects/{project_id}/files`        | 项目文件沙箱 list/read/write/find/patch/export                |
| `librarian`       | `/api/v1/librarian`                          | search、matrix、deep-dive、global-finder、query-builder       |
| `data_process`    | `/api/v1/data-process`                       | 任务列表、详情、取消、重试、删除                              |
| `data_process_ws` | `/api/v1/ws/data-process`                    | Data Process 任务实时事件                                     |
| `conversation`    | `/api/v1/conversations`                      | 会话与消息 CRUD、fork、turn 删除                              |
| `conversation_ws` | `/api/v1/ws/conversations/{conversation_id}` | ResearcherAgent 流式对话                                      |
| `hitl_ws`         | `/api/v1/ws/hitl`                            | Human-in-the-loop 问题广播与回答                              |
| `agent_traces`    | `/api/v1/agent-traces`                       | trace 查询、列表、删除                                        |
| `settings`        | `/api/v1/settings`                           | LLM provider、Agent LLM、MinerU、Data Process、Librarian 配置 |

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
- `src/paper_plane_x_backend/services/conversation/`
- `src/paper_plane_x_backend/services/data_process_tasks/`
- `src/paper_plane_x_backend/services/librarian/`

职责：

- SQLite 初始化与轻量迁移。
- Paper / Project / Conversation / Trace 数据访问。
- Data Process 任务持久化与 worker 生命周期。
- Librarian 字段读取、搜索和矩阵组装。

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

`Tool.execute` 的隐藏上下文参数使用 `runtime_context` 注入，例如 `project_id`、`conversation_id`、caller 信息。不要使用旧的 `context=` 形态。

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

## 4. ResearcherAgent

入口：

- Conversation WebSocket：`/api/v1/ws/conversations/{conversation_id}`
- Conversation REST：`/api/v1/conversations/*`

ResearcherAgent 是项目级对话 agent。它的运行上下文包含：

- `project_id`
- `conversation_id`
- 当前 conversation memory
- Tool runtime context

内置工具：

- 项目文件沙箱：`read_project_file`、`read_project_file_lines`、`find_in_project_file`、`write_project_file`、`replace_project_file_lines`、`replace_project_file_text`、`patch_project_file`、`list_project_files`、`remove_project_file`
- Librarian：`global_finder`、`search_paper`、`matrix_compare`、`deep_dive`
- Paper note：`get_paper_agent_note`、`write_paper_agent_note`、`update_paper_agent_note`、`delete_paper_agent_note`
- 内部协作能力：`delegate_to_subagent`
- 人机交互：`ask_human`

`SubAgent` 拥有接近 ResearcherAgent 的工具集，但不允许继续调用 `delegate_to_subagent`，避免递归委派。

## 5. HITL

入口：

- WebSocket：`/api/v1/ws/hitl`
- Tool：`ask_human`

流程：

1. ResearcherAgent 调用 `ask_human`。
2. `HITLManager` 注册 pending question。
3. 所有 HITL WebSocket 客户端收到 `hitl_question`。
4. 用户提交 `answer`。
5. `ask_human` 返回答案给 Agent。
6. 默认 10 分钟超时保护。

## 6. Librarian

入口：

- `POST /api/v1/librarian/search`
- `POST /api/v1/librarian/matrix`
- `POST /api/v1/librarian/deep-dive`
- `POST /api/v1/librarian/global-finder`
- `POST /api/v1/librarian/query-builder`
- `POST /api/v1/projects/{project_id}/search`

核心数据来自 `papers` 表中的：

- `md_content`
- `quick_scan`
- `synthesis_data`
- `analysis_report`
- 论文元数据字段

Librarian 使用 DSL 查询和 field_paths 做精确提取。详见 [librarian.md](./librarian.md)。

## 7. `ppx` CLI 与 Researcher Skill

### `ppx` CLI

入口：

- `../../paper_plane_x_cli/src/paper_plane_x_cli/cli.py`
- console script：`ppx = "paper_plane_x_cli.cli:main"`
- 本地安装：`uv tool install ../paper_plane_x_cli`（从 backend 目录执行）
- 一次性运行：`uvx --from ../paper_plane_x_cli ppx --help`（从 backend 目录执行）

特点：

- 只通过 HTTP 调 FastAPI。
- 不 import tools，不读写 DB。
- 输出 JSON，方便 Codex / Claude Code / shell 脚本解析。
- context 优先级：命令参数 > 环境变量 > `~/.config/paper-plane-x/context.json` > 默认 base URL。

常用：

```bash
ppx context set --base-url http://127.0.0.1:8000/api/v1 --project-id prj_x
ppx project global-finder
ppx librarian search --query-expr "(meta.title CONTAINS transformer)"
ppx files list --dir /
```

### Researcher Skill

目录：

- `../../paper_plane_x_cli/skills/paper-plane-x-researcher/SKILL.md`
- `../../paper_plane_x_cli/skills/paper-plane-x-researcher/references/tool-guide.md`

用途：

- 让外部 agent 获得接近内置 ResearcherAgent 的工作原则、工具语义、field_paths、query rules 和 CLI 调用方式。
- 不暴露内部 `ask_human` 和 `delegate_to_subagent` 工具。
- 外部 agent 需要确认时直接问当前用户；复杂任务拆分由宿主 agent 自己处理。

## 8. 数据模型与存储

主存储：SQLite。

关键表：

- `projects`
- `papers`
- `paper_projects`
- `data_process_tasks`
- `agent_traces`
- `conversations`
- `conversation_messages`
- `papers_fts`

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

## 9. 配置与运行时文件

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

决定 Agent 调谁、用什么模型、MinerU 在哪。
通过 Settings API 或 `data/app_settings.toml` 读写，服务启动后随时可改。
包含：LLM Provider 列表、Agent LLM 绑定、MinerU 地址、Data Process 参数、Librarian 参数。

首次启动后必须先配 Provider 和 Agent LLM，否则所有需要 LLM 的操作都会失败。

常见运行时文件：

- `data/app.db`
- `data/papers/`
- `data/projects/`
- `data/logs/`
- `data/console/`

后端 console 静态资源查找顺序：

1. `settings.api.console_dist_dir`
2. `../paper_plane_x_frontend/dist`

## 10. 开发维护原则

- API 层保持薄：校验、依赖注入、HTTP 映射。
- 业务组合放 orchestrator。
- 数据访问放 repository。
- Agent 工具说明要同步到 Researcher prompt 和 external skill。
- 新 API 必须补 integration test。
- 修改 tool context 语义时必须跑 agent runtime tests。
- 文档里不保留已经删除的路由或旧设计草稿。
