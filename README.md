# Paper Plane X Backend

Paper Plane X 后端负责整个数据处理主链路：

- 接收 PDF 上传
- 调用解析与 Agent 处理流程
- 管理项目、论文、任务、追踪信息
- 提供控制台与 Zotero 插件依赖的 API
- 持久化 SQLite 数据与结构化处理结果

如果你只想快速跑起来，先看“快速开始”。  
如果你想理解系统结构，再看 [docs/README.md](./docs/README.md)。

## 1. 后端负责什么

当前后端提供四类核心能力：

1. **项目与论文管理**
   - Project CRUD
   - Paper CRUD
   - Project 与 Paper 的关联管理

2. **Data Process 异步处理**
   - 上传 PDF
   - 后台 worker 消费任务
   - 解析、提炼、核查、落库
   - 失败 / 取消任务重试

3. **追踪与审计**
   - 保存原始 PDF 路径
   - 保存 Agent trace、LLM usage 与 fact check 结果
   - 保持结构化结果可人工修改

4. **控制台与检索 API**
   - 控制台所需的项目、任务、导出接口
   - Librarian 字段投影、矩阵对比、项目内搜索

5. **论文对话学习**
   - Teacher 会话式学习 Agent
   - 单篇论文上下文注入
   - 会话历史与 trace 追踪

## 2. 快速开始

### 2.1 前置条件

- Python 3.12+
- `uv`
- 本地可用的 SQLite
- 如果要跑完整 PDF 处理链，建议准备好 MinerU 服务

### 2.2 本地开发启动

```bash
cd paper_plane_x_backend
uv sync
cp .env.example .env
./scripts/dev_api.sh
```

默认地址：

- API / Console：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/health`

### 2.3 快速验证

```bash
curl -s http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok","app_name":"Paper Plane X"}
```

## 3. 开发命令

### 3.1 推荐命令

```bash
# 开发启动
./scripts/dev_api.sh

# 测试
./scripts/test.sh

# Lint
uv run ruff check .

# Type check
uv run pyright
```

### 3.2 其他常用命令

```bash
# 仅跑某一组测试
./scripts/test.sh tests/unit/test_config_settings.py

# 构建前端 console 到 backend data 目录
./scripts/build_console.sh
```

## 4. API 概览

### 4.1 Project

- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `DELETE /api/v1/projects/{project_id}`
- `GET /api/v1/projects/{project_id}/papers`
- `POST /api/v1/projects/{project_id}/papers/{paper_id}`
- `DELETE /api/v1/projects/{project_id}/papers/{paper_id}`
- `POST /api/v1/projects/{project_id}/search`
- `POST /api/v1/projects/{project_id}/export`

### 4.2 Paper

- `POST /api/v1/papers`
- `GET /api/v1/papers`
- `GET /api/v1/papers/{paper_id}`
- `PATCH /api/v1/papers/{paper_id}`
- `POST /api/v1/papers/{paper_id}/reprocess`
- `DELETE /api/v1/papers/{paper_id}`

### 4.3 Data Process Tasks

- `GET /api/v1/data-process/tasks`
- `GET /api/v1/data-process/tasks/{task_id}`
- `POST /api/v1/data-process/tasks/{task_id}/cancel`
- `POST /api/v1/data-process/tasks/{task_id}/retry`
- `DELETE /api/v1/data-process/tasks/{task_id}`

### 4.4 Trace

- `POST /api/v1/agent-traces/query`
- `DELETE /api/v1/agent-traces/{trace_id}`

### 4.5 Librarian

- `GET /api/v1/librarian/guide`
- `POST /api/v1/librarian/global-finder`
- `POST /api/v1/librarian/search`
- `POST /api/v1/librarian/projection`
- `POST /api/v1/librarian/matrix`

### 4.6 Teacher

- `GET /api/v1/teacher/conversations`
- `POST /api/v1/teacher/conversations`
- `GET /api/v1/teacher/conversations/{conversation_id}`
- `PATCH /api/v1/teacher/conversations/{conversation_id}`
- `DELETE /api/v1/teacher/conversations/{conversation_id}`
- `POST /api/v1/teacher/conversations/{conversation_id}/run`

## 5. 配置说明

后端配置由 `Settings` 统一管理，配置来源优先级如下：

1. 初始化参数
2. 系统环境变量
3. `.env`
4. `PPX_CONFIG_FILE` 指向的 TOML 文件
5. 默认配置文件

### 5.1 配置 profile

仓库中已提交的 profile：

- `config/default.toml`：默认基线配置
- `config/dev.toml`：本地开发配置
- `config/test.toml`：测试环境配置

通过下面的环境变量切换：

```bash
export PPX_CONFIG_FILE=./config/dev.toml
```

### 5.2 常用环境变量

- `PPX_CONFIG_FILE`
- `PPX_DATABASE_PATH`
- `PPX_PROMPTS_DIR`
- `PPX_API__HOST`
- `PPX_API__PORT`
- `PPX_API__RELOAD`
- `PPX_API__CORS_ALLOW_ORIGINS`
- `PPX_LLM__API_KEY`
- `PPX_MINERU__BASE_URL`
- `PPX_MINERU__OUTPUT_DIR`
- `PPX_DATA_PROCESS__WORKER_COUNT`

### 5.3 本地自定义建议

推荐在以下位置做本机定制：

- `.env`
- `config/*.local.toml`

不要直接改动已经提交的 `dev.toml` / `test.toml` 来保存个人机器特有配置。

## 6. 目录结构

```text
paper_plane_x_backend/
├── config/              # TOML 配置 profile
├── docs/                # 详细文档
├── prompts/             # Agent prompt 文件
├── scripts/             # 开发、测试、构建辅助脚本
├── src/paper_plane_x_backend/
│   ├── api/             # FastAPI routers / dependencies
│   ├── agents/          # Agent 定义
│   ├── core/            # agent runtime 等基础能力
│   ├── models/          # 核心数据模型
│   ├── schemas/         # API / Agent IO schemas
│   ├── services/        # database / orchestrators / paper services
│   └── utils/           # 日志等工具
└── tests/               # 单元与集成测试
```

## 7. 数据与运行时文件

默认情况下，运行时数据放在 `data/` 目录下，包括：

- SQLite 数据库
- 原始 PDF 与解析产物
- 日志文件
- 前端 console 构建产物

常见子目录：

- `data/app.db`
- `data/papers/`
- `data/logs/`
- `data/console/`

## 8. Docker 部署

后端已经提供 Docker 相关文件：

- [Dockerfile](./Dockerfile)
- [docker-compose.yml](./docker-compose.yml)
- [.dockerignore](./.dockerignore)
- [.env.docker.example](./.env.docker.example)

### 8.1 最简启动

```bash
cd paper_plane_x_backend
cp .env.docker.example .env.docker
docker compose up --build -d
```

默认暴露：

- `http://127.0.0.1:8000`

### 8.2 部署说明

- Compose 会挂载 `./data` 持久化数据库、文件和日志
- 默认使用 `config/default.toml`
- 如需替换配置 profile，可在 `.env.docker` 中调整 `PPX_CONFIG_FILE`
- MinerU 当前按外部服务处理，如需启用，请在 `.env.docker` 中配置 `PPX_MINERU__BASE_URL`

## 9. 文档入口

- [docs/README.md](./docs/README.md)
- [docs/workflow_quickstart.md](./docs/workflow_quickstart.md)
- [docs/architecture.md](./docs/architecture.md)
- [docs/teacher.md](./docs/teacher.md)
- [tests/README.md](./tests/README.md)

## 10. 常见问题

### 启动后没有 console 页面

后端会优先尝试读取：

1. `settings.api.console_dist_dir`
2. `../paper_plane_x_frontend/dist`

如果这两个位置都没有前端构建产物，根路径只会返回 `404 Console build not found`。

### 上传能成功但任务最终失败

通常优先检查：

- MinerU 地址是否可用
- LLM API key 是否正确
- 后端日志里是否有具体堆栈

### 为什么项目内部没有 paper 详情 GET 路由

当前设计里：

- 论文详情由顶层 `/api/v1/papers/{paper_id}` 提供
- `/api/v1/projects/{project_id}/papers/{paper_id}` 只用于 link / unlink

这样可以避免重复定义“同一篇论文详情”的两套路由语义
