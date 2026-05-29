# Backend Testing Guide

这份文档说明测试目录如何组织、如何运行，以及新增功能时应该补哪些测试。

当前基线：`362 passed`。

## 1. 测试分层

- `tests/unit/`
  - 验证单个函数、类、repository、runtime、工具、配置。
  - 不依赖真实 HTTP 路由。
- `tests/integration/`
  - 使用 `TestClient` 验证 API、依赖注入、数据库交互和业务路径。
  - 覆盖 router + orchestrator + repository 的组合行为。
- `tests/conftest.py`
  - 测试数据库、TestClient、task manager、LLM provider/app settings fixture。

## 2. 当前覆盖重点

### Unit

- Agent runtime / LLM client / memory / tooling
- Tool context injection
- `DataProcessTaskManager`
- `Database` schema 初始化与迁移
- `PaperRepository`
- `ProjectRepository`
- `ConversationRepository`
- `PaperProcessor`
- `PaperParser`
- `Settings` 配置合并
- `ppx` CLI context 解析、HTTP 请求构造、错误输出

### Integration

- App health
- Project API
- Paper API
- Paper agent note API
- Project files API
- Data Process task API
- Librarian API
- Conversation API + WebSocket
- HITL WebSocket
- Agent traces API
- Settings API

## 3. 推荐执行方式

全量测试：

```bash
cd paper_plane_x_backend
./scripts/test.sh
```

指定文件：

```bash
uv run --project ../paper_plane_x_cli pytest ../paper_plane_x_cli/tests/test_cli.py
./scripts/test.sh tests/integration/test_librarian_api.py
```

常用回归：

```bash
uv run ruff check .
uv run pyright
./scripts/test.sh
```

如果在受限沙箱里运行，`uv` 可能需要写 cache；此时需要允许 `uv run ...` 使用 cache 目录。

## 4. 新增功能时补什么测试

### 新 API

补 integration test，验证：

- 成功响应。
- 404 / 400 / 422 等关键错误。
- 数据库状态变化。
- response model 的关键字段。

### 新 repository / service 行为

补 unit test，验证：

- 正常路径。
- 边界值。
- 领域错误。
- 迁移或兼容逻辑。

### 新 Agent tool

补 unit test，验证：

- tool schema 生成。
- `runtime_context` 注入。
- 成功与错误 payload。
- shared guide 是否包含必要说明。

同时更新：

- `prompts/researcher/System.md`
- `../paper_plane_x_cli/skills/paper-plane-x-researcher/SKILL.md`
- `../paper_plane_x_cli/skills/paper-plane-x-researcher/references/tool-guide.md`
- `docs/librarian.md`

### 新 `ppx` CLI 命令

在兄弟包 `../paper_plane_x_cli` 中补 unit test，验证：

- CLI 参数。
- context 优先级。
- HTTP method / path / JSON body / query params。
- 错误输出到 stderr 且返回非零退出码。

同时更新：

- `README.md`
- `docs/workflow_quickstart.md`
- `docs/librarian.md`
- `../paper_plane_x_cli/skills/paper-plane-x-researcher/references/tool-guide.md`

## 5. 测试环境约定

- 测试使用临时运行目录，不污染开发数据。
- 测试数据库由 fixture 初始化。
- `TestClient` 通过 dependency override 注入测试 DB 与测试 task manager。
- LLM provider/app settings 在测试启动时写入测试配置。
- 大多数 agent 相关测试 mock LLM 响应，不依赖真实外部模型。

## 6. 命名约定

- 文件名：`test_*.py`
- 测试名描述行为，而不是实现细节。
- 修 bug 时，优先写最小复现测试。
- API 测试按 router 放在 `tests/integration/test_*_api.py`。

## 7. 维护原则

- 修改路由语义，更新对应 integration tests。
- 修改 schemas，检查 response model 和 pyright。
- 修改 tool runtime，至少跑 `test_agent_runtime*` 和相关 `test_tools_*`。
- 修改 data-process，至少跑 data-process API、task manager、orchestrator 相关测试。
- 修改 docs/skill/CLI，不一定需要全量测试，但至少跑受影响的 CLI/API 单元或集成测试。
