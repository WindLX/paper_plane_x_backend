# Paper Plane X Backend

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)

Paper Plane X Backend 是 Paper Plane X 的核心服务。它提供 FastAPI HTTP/WebSocket API，负责项目与论文管理、PDF 解析、结构化抽取、事实核查、文献检索、项目文件、运行时设置和 Agent 调用追踪。

Web 控制台、`ppx` CLI、Zotero 插件和外部 Agent Skills 都通过该服务访问数据，不应直接读写数据库。

## 主要能力

- **Paper pipeline**：上传 PDF，保存解析后的 Markdown，运行 Extraction、Analysis 和 Fact Check。
- **Project workspace**：维护项目元数据、关联论文、项目文件和项目导出，并提供只读项目总览、持久活动历史与后台 ZIP 导出任务。
- **Librarian**：全局发现、DSL 搜索、字段矩阵、query builder 和单篇 deep dive。
- **Background tasks**：管理并通过 WebSocket 推送数据处理任务状态。
- **Runtime Settings**：配置 LLM Provider、Agent LLM、PDF Parser、Pandoc、worker 和 Librarian。
- **Agent traces**：记录 LLM 请求、工具调用、token 使用和运行错误。
- **Console hosting**：可直接托管构建后的 Vue Web 控制台。
- **Local persistence**：默认使用 SQLite 与本地数据目录，无需外部数据库。

## 运行要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- 一个可访问的 PDF Parser：本地 MinerU 或 MinerU Cloud
- 至少一个与 OpenAI API 兼容的 LLM Provider（使用 Agent 能力时必需）
- 可选：[Pandoc](https://pandoc.org/) 与 PDF engine，用于项目文件导出；导出包含 SVG 的项目文件还需要 `rsvg-convert`
- 可选：Docker / Docker Compose

## 安装与运行

### 方式一：Backend + Web Console（推荐）

普通用户只需克隆 backend，并使用 monorepo Release 中已经构建好的 Web Console：

```bash
git clone https://github.com/WindLX/paper_plane_x_backend.git
cd paper_plane_x_backend
uv sync
cp .env.example .env
mkdir -p data/console
```

从 [Paper Plane X 最新 Release](https://github.com/WindLX/paper_plane_x/releases/latest) 下载 `paper-plane-x-console-vX.Y.Z.tar.gz`，解压后启动服务：

```bash
tar -xzf paper-plane-x-console-vX.Y.Z.tar.gz -C data/console
uv run app
```

这种方式不需要 Node.js。backend 会在同一个 `8000` 端口提供 API 和 Web Console。

默认地址：

- 服务：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/health`
- OpenAPI：`http://127.0.0.1:8000/docs`

```bash
curl -fsS http://127.0.0.1:8000/health
```

调试模式：

```bash
uv run debug
```

### 方式二：Docker Compose

发布镜像已经内置对应版本的 Web Console。只克隆 backend 仓库即可使用随仓库提供的 Compose 配置：

```bash
git clone https://github.com/WindLX/paper_plane_x_backend.git
cd paper_plane_x_backend
GHCR_OWNER=windlx PPX_VERSION=latest \
  docker compose -f docker-compose.release.yml up -d
```

也可以参照顶层 [Paper Plane X README](https://github.com/WindLX/paper_plane_x#面向用户安装与运行) 创建独立的 Compose 配置。

### 方式三：从 monorepo 源码运行

该方式适合同时修改 backend 和 frontend 的开发者：

```bash
git clone --recursive https://github.com/WindLX/paper_plane_x.git
cd paper_plane_x
just setup
cp paper_plane_x_backend/.env.example paper_plane_x_backend/.env
just build-console
just backend dev
```

如需从源码构建 Docker 镜像，Dockerfile 的 build context 必须是 monorepo 根目录：

```bash
docker compose -f paper_plane_x_backend/docker-compose.yml up --build -d
```

## Web 控制台

后端按以下顺序查找前端构建产物：

1. `api.console_dist_dir`，默认 `./data/console`；
2. monorepo 中的 `../paper_plane_x_frontend/dist`。

从 monorepo 根目录构建 backend-hosted console：

```bash
just build-console
just backend dev
```

或在 backend 目录中执行：

```bash
just build-console
```

## 配置模型

Paper Plane X 将启动配置与运行时设置分开管理。

### ServerConfig：启动时配置

优先级从高到低：

1. 代码初始化参数；
2. `PPX_*` 环境变量；
3. `.env`；
4. `PPX_CONFIG_FILE` 指向的 TOML，默认 [`config/default.toml`](config/default.toml)；
5. 文件密钥源。

常用环境变量：

```dotenv
PPX_CONFIG_FILE=./config/default.toml
PPX_API__HOST=0.0.0.0
PPX_API__PORT=8000
PPX_DATA_DIR=./data
PPX_DATABASE_PATH=./data/app.db
PPX_LOG__LEVEL=INFO
```

ServerConfig 修改后需要重启服务。

### AppSettings：运行时设置

AppSettings 通过 Web Settings 页面或 `/api/v1/settings` API 修改，并持久化到 `data/app_settings.toml`。主要设置包括：

- LLM Provider 与 API key；
- 各 Agent 的 Provider、temperature、token、timeout 和 reasoning 参数；
- 本地或云端 MinerU；
- Data Process worker、重试与超时；
- Librarian 参数；
- Pandoc 路径、HTML template 和 PDF engine。

这些设置通常即时生效，无需重启。

## 首次配置

推荐通过 Web 控制台完成。也可以直接调用 API：

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/v1/settings/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "default",
    "model": "your-model",
    "api_key": "your-api-key",
    "base_url": "https://provider.example/v1"
  }'
```

绑定 Agent：

```bash
for agent in extraction analysis fact_check deep_diver query_builder global_finder; do
  curl -fsS -X PUT \
    "http://127.0.0.1:8000/api/v1/settings/agent_llm/${agent}" \
    -H "Content-Type: application/json" \
    -d '{"provider_name":"default"}'
done
```

不要在脚本、Issue、日志或提交中暴露真实 API key。

## 数据目录与备份

默认数据目录是 `./data`：

| 路径                | 内容                          |
| ------------------- | ----------------------------- |
| `app.db`            | SQLite 数据库                 |
| `app_settings.toml` | 运行时设置与密钥              |
| `papers/`           | PDF 解析结果、Markdown 和图片 |
| `projects/`         | 项目文件沙箱                  |
| `logs/`             | 后端日志与轮转文件            |
| `console/`          | 可选 Web 控制台构建产物       |

生产部署至少应备份数据库、`app_settings.toml`、`papers/` 和 `projects/`。数据目录可能包含论文原文、模型密钥和研究内容，应限制文件权限并避免公开挂载。

## API 概览

业务 API 默认位于 `/api/v1`：

| 模块          | 路径前缀               | 说明                                     |
| ------------- | ---------------------- | ---------------------------------------- |
| Paper         | `/papers`              | 上传、查询、重处理、Markdown、Agent note |
| Project       | `/projects`            | 项目 CRUD、论文关联和导出                |
| Project Workbench | `/projects/{id}/overview`、`/projects/{id}/activities` | 只读总览与活动历史 |
| Project Exports | `/projects/{id}/exports` | 后台导出的提交、查询、取消与下载 |
| Project Files | `/projects/{id}/files` | 文件 list/read/write/patch/upload/export、原字节下载与图片预览 |
| Librarian     | `/librarian`           | 搜索、矩阵、deep dive、query builder     |
| Data Process  | `/data-process`        | 后台任务查询与取消                       |
| Settings      | `/settings`            | Provider、Agent、Parser、Pandoc 等设置   |
| Agent Traces  | `/agent-traces`        | Agent 调用记录与查询                     |
| PDF Parse     | `/parse`               | 独立 PDF 转 Markdown API                 |

完整请求与响应模型以运行中服务的 `/docs` 为准。

## CLI 与外部 Agent

安装已发布 CLI：

```bash
uv tool install paper-plane-x-cli
ppx context set \
  --base-url http://127.0.0.1:8000/api/v1 \
  --project-id prj_x
ppx context show
```

CLI 与 Skills 的完整说明见 [`paper_plane_x_cli`](https://github.com/WindLX/paper_plane_x_cli)。

## 开发与测试

推荐命令：

```bash
just setup
just dev
just lint
just format-check
just typecheck
just test
just build
just pre-commit
```

直接使用 uv：

```bash
uv sync
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright
uv run pytest
uv build
```

测试分为 `tests/unit` 与 `tests/integration`。行为变更应优先补充对应测试；API 变更还应更新 schema、前端类型和相关文档。

## 贡献与 Pull Request

1. 从最新 `main` 创建功能分支。
2. 保持改动聚焦，并遵循现有类型与日志约定。
3. 新增或修改行为时补充测试。
4. 路由、配置或命令变更时同步更新 README 或 `docs/`。
5. 提交前运行 `just pre-commit`。
6. PR 描述中列出动机、API/数据兼容性、验证命令和必要的迁移步骤。

请勿提交 `.env`、`data/`、数据库、日志、证书、模型密钥或论文私有数据。

## 更多文档

- [Workflow Quickstart](docs/workflow_quickstart.md)
- [Architecture](docs/architecture.md)
- [Librarian](docs/librarian.md)
- [Project Workbench](docs/project-workbench.md)
- [Logging Conventions](docs/logging_conventions.md)
- [MinerU Cloud API](docs/mineru_cloud_api.md)
- [Roadmap](docs/roadmap.md)
- [Issues](https://github.com/WindLX/paper_plane_x_backend/issues)

## License

Paper Plane X Backend 使用 [GNU Affero General Public License v3.0 or later](LICENSE)。分发修改版本或通过网络向用户提供修改后的服务时，请遵守 AGPL-3.0-or-later。

## MinerU 4 migration / MinerU 4 迁移

Local parsing requires MinerU 4.x V1. See [migration and on-demand deployment](docs/mineru_v4.md) for the request contract, cold startup, and idle shutdown. 本地解析要求 MinerU 4.x V1；配置与按需部署说明见上述文档。


六个 Agent 的单次请求总 Token 预算默认均为 **240000**，使用 `max_total_tokens`；后端自动计数并计算剩余输出空间，无需配置 tokenizer。旧 `max_tokens` 用户配置已移除，升级时需要清理旧字段，详见 [Token 预算说明](docs/token_budget.md)。
