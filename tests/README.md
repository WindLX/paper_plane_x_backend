# Backend Testing Guide

这份文档说明后端测试目录如何组织、平时怎么跑，以及新增测试时该放哪里。

## 1. 测试分层

当前测试分成两层：

- `tests/unit/`
  - 纯单元测试
  - 重点验证函数、类、配置合并、数据库逻辑、Agent runtime 细节
- `tests/integration/`
  - API 与业务编排集成测试
  - 重点验证路由、依赖注入、数据库交互与主流程

共享 fixture 放在：

- `tests/conftest.py`

## 2. 当前覆盖重点

### 2.1 Unit

- Agent runtime / LLM client / memory / tooling
- `DataProcessTaskManager`
- `Database` schema 初始化与迁移
- `PaperRepository`
- `PaperProcessor`
- `PaperParser`
- `Settings` 配置合并与 profile 行为

### 2.2 Integration

- `Project` API
- `Paper` API
- `Data Process` task API
- `App health`
- `Librarian` API
- `Conversation` API + WebSocket
- `HITL` WebSocket

## 3. 推荐执行方式

### 3.1 全量测试

```bash
cd paper_plane_x_backend
./scripts/test.sh
```

### 3.2 跑指定文件

```bash
./scripts/test.sh tests/unit/test_config_settings.py
./scripts/test.sh tests/integration/test_project_api.py
```

### 3.3 推荐本地回归顺序

```bash
uv run ruff check .
uv run pyright
./scripts/test.sh
```

## 4. 测试环境约定

测试运行时会使用测试专用运行目录和测试安全配置，不应污染你的日常开发数据。

当前测试重点约束：

- 临时数据目录独立
- 日志输出可控
- 测试数据库与开发数据库隔离
- 测试 client 通过依赖覆盖注入测试 DB 与测试 task manager

## 5. 新增测试时怎么判断位置

### 放进 `unit/` 的情况

- 不依赖 HTTP 路由
- 只验证单个类、函数或模块行为
- 只需要 mock / fixture，不需要完整 app lifecycle

### 放进 `integration/` 的情况

- 需要 `TestClient`
- 需要真实 router / dependency / database 交互
- 需要验证一条完整业务路径

## 6. 命名约定

- 文件名使用 `test_*.py`
- 测试名描述行为，不描述实现细节
- 修 bug 时，优先补最小可复现测试

## 7. 维护原则

- 如果修改了配置系统，优先更新 `test_config_settings.py`
- 如果修改了路由语义，优先更新对应 integration tests
- 如果修改了数据库结构或迁移逻辑，优先更新 `test_database_service.py`
