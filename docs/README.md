# Paper Plane X Backend Docs

这组文档面向两类读者：

- **用户 / 外部 Agent 使用者**：想启动服务、上传论文、检索项目文献、使用兄弟包 `../paper_plane_x_cli` 提供的 `ppx` CLI 或 `ppx-researcher` skill。
- **开发者**：想理解后端结构、扩展 API / Agent / tools、维护测试和部署。

## 建议阅读顺序

1. [../README.md](../README.md)
   - 项目能力、启动方式、核心 API、CLI 与 skill 入口。
2. [workflow_quickstart.md](./workflow_quickstart.md)
   - 从零验证服务：创建项目、上传 PDF、关联项目、使用 Librarian、使用 `ppx`、Project files 与 paper notes。
3. [librarian.md](./librarian.md)
   - 文献检索、field_paths、matrix、deep-dive、paper note、project files、`ppx` 映射。
4. [architecture.md](./architecture.md)
   - 当前后端分层、数据流、Agent runtime、CLI/skill 边界。
5. [logging_conventions.md](./logging_conventions.md)
   - 日志字段、事件命名、排障建议。
6. [roadmap.md](./roadmap.md)
   - 当前实现状态和下一步方向。
7. [../tests/README.md](../tests/README.md)
   - 测试结构、运行方式、在哪里补测试。

本地 MinerU 4.x 的接口迁移、模型与按需服务部署见 [mineru_v4.md](mineru_v4.md)。

Agent 配置与自动输出预算见 [token_budget.md](token_budget.md)。

## 文档分工

### `README.md`

项目首页，包括：

- 如何启动
- 当前真实 API 列表
- `ppx` CLI 入口
- `ppx-researcher` skill 入口
- 配置、目录结构、常见问题

### `workflow_quickstart.md`

端到端上手文档。用于验证服务：

- Health check
- 创建项目
- 上传 PDF
- 关联项目
- 查任务、查论文
- Librarian API
- `ppx` CLI
- Project files / paper notes
- Project files / paper notes

### `librarian.md`

检索与外部 agent 使用手册：

- `query_expr` 语法
- `field_paths`
- `global-finder` / `search` / `matrix` / `deep-dive`
- Project files 和 paper notes
- `ppx` CLI 到 Researcher tools 的映射
- `../paper_plane_x_cli/skills/ppx-researcher` 的定位

### `architecture.md`

当前实现：

- FastAPI router 分组
- Orchestrator / service / repository 边界
- Data Process 流程
- Agent runtime 与当前后端 Agent
- `ppx` CLI 和 skill 如何复用后端能力

### `roadmap.md`

状态快照，用于同步：

- 已完成能力
- 进行中风险
- 下一步优先事项

## 维护原则

- README 负责入口和当前正确路径。
- `docs/` 负责机制和细节。
- 不在正文保留已删除接口、旧命令、旧设计草稿。
- 新增或删除 API 时，同步更新：
  - [../README.md](../README.md)
  - [workflow_quickstart.md](./workflow_quickstart.md)
  - [architecture.md](./architecture.md)
  - [librarian.md](./librarian.md)（如果影响检索/Researcher/CLI）
- 修改测试方式时，同步更新 [../tests/README.md](../tests/README.md)。
