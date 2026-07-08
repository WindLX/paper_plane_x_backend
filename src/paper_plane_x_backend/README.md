# `paper_plane_x_backend` Package Guide

该目录是后端核心代码包，按 API、业务编排、服务、Agent runtime、tools、schemas 分层组织。

## 目录结构

- `main.py`
  - FastAPI app 入口，注册 routers，管理 lifespan。
- `api/routers/`
  - HTTP / WebSocket 路由：project、paper、project_files、librarian、data_process、data_process_ws、agent_traces、settings、pdf_parser。
- `api/dependencies.py`
  - FastAPI 依赖注入，主要提供数据库和 task manager。
- `services/orchestrators/`
  - 业务编排入口：project、paper、data_process、librarian。
- `services/`
  - 数据库、repository、任务管理、PDF 解析、Librarian 服务、project files、settings。
- `core/agent_runtime/`
  - BaseAgent、LLMClient、tooling、memory、stream types、输出校验。
- `agents/`
  - DataProcessorAgentGroup、QueryBuilder、GlobalFinder、DeepDiver。
- `tools/`
  - Agent 可调用工具：project file I/O、librarian、paper。
- `schemas/`
  - API schemas 与 Agent I/O schemas。
- `models/`
  - 核心领域模型与枚举。
- `../paper_plane_x_cli/src/paper_plane_x_cli/cli.py`
  - `ppx` HTTP CLI 位于兄弟包 `paper_plane_x_cli`，供外部 agent 和脚本调用后端能力。

## 核心链路

### Data Process

1. `POST /api/v1/papers` 接收 PDF 上传。
2. `PaperOrchestrator` 创建或复用 paper，启动 data-process task。
3. `DataProcessTaskManager` 持久化任务并交给 worker pool。
4. `PaperParser` 生成 Markdown / 图片。
5. `DataProcessorAgentGroup` 执行 Extraction / Analysis / Fact Check。
6. `PaperProcessor` 写回 `papers` 表。

关键文件：

- `api/routers/paper.py`
- `api/routers/data_process.py`
- `services/orchestrators/paper.py`
- `services/orchestrators/data_process.py`
- `services/data_process_tasks/`
- `services/paper/parser.py`
- `services/paper/processor.py`
- `services/paper/repository.py`

### Project Files

1. Project 创建时初始化独立文件沙箱。
2. `project_files` API 提供 list/read/write/upload/replace/patch/delete/export。
3. 外部 `ppx` CLI 和 agent skill 通过 HTTP API 读写项目笔记、草稿和中间产物。
4. 旧 conversation 表在数据库初始化时备份后迁移删除。

关键文件：

- `api/routers/project_files.py`
- `services/project/files.py`
- `tools/conversation_io.py`
- `services/database.py`

### Librarian

1. `search` 用 DSL 返回 `paper_ids`。
2. `matrix` 按 `paper_ids` 和 `field_paths` 拉取结构化字段。
3. `global-finder` 聚合项目论文概览和统计。
4. `deep-dive` 调用 DeepDiverAgent 回答单篇论文问题。

关键文件：

- `api/routers/librarian.py`
- `services/orchestrators/librarian.py`
- `services/librarian/`
- `tools/librarian.py`
- `schemas/api/librarian.py`

### External Agent Integration

`ppx` CLI 是外部 agent 的稳定调用面：

- `ppx context show/set`
- `ppx project global-finder`
- `ppx librarian search/matrix/deep-dive`
- `ppx files list/read/lines/find/write/upload/replace-lines/replace-text/patch/delete`
- `ppx paper-note get/write/delete`

Skill 目录：

- `../paper_plane_x_cli/skills/ppx-researcher/SKILL.md`
- `../paper_plane_x_cli/skills/ppx-researcher/references/tool-guide.md`
- `../paper_plane_x_cli/skills/ppx-pdf-to-markdown/SKILL.md`

## 代码约定

- API 层保持薄：参数校验、依赖注入、HTTP 错误映射。
- 业务流程放 orchestrator。
- 数据访问放 repository，不使用 ORM。
- Agent tool 的隐藏上下文使用 `runtime_context` 注入。
- Agent 输出必须通过 schema 校验。
- 关键流程日志使用 `event=` 字段。
- 新 API、新 CLI、新 tool 需要同步测试和文档。CLI 代码与测试维护在兄弟包 `paper_plane_x_cli`。

## Console 前端集成

后端会尝试托管已构建的前端 console：

1. `settings.api.console_dist_dir`
2. `../paper_plane_x_frontend/dist`

构建快捷命令：

```bash
./scripts/build_console.sh
```

如果没有构建产物，根路径会返回 `404 Console build not found`，API 不受影响。
