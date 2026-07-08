# Paper Plane X Backend

Paper Plane X Backend 是整个系统的核心服务。它提供 FastAPI HTTP API，用于管理项目、上传和处理论文、解析 PDF、运行结构化抽取与事实核查、查询文献、读写项目文件，以及保存运行时设置。

前端控制台、`ppx` CLI、Zotero 插件和外部 Agent skills 都通过这个后端工作。

## 能力概览

- Project：创建研究项目，关联论文，导出项目数据和项目文件。
- Paper：上传 PDF、保存 Markdown、查看结构化处理结果、维护 paper note。
- Data Process：管理 PDF 解析、Extraction、Analysis、Fact Check 后台任务。
- Librarian：项目总览、DSL 检索、字段矩阵、自然语言 query builder、单篇 deep dive。
- Project files：项目沙箱文件的 list/read/write/upload/patch/export。
- Settings：运行时维护 LLM Provider、Agent LLM、PDF Parser、Data Process 和 Librarian 设置。
- Agent traces：查看 LLM 调用、工具调用和 token 使用记录。

## 启动

本地运行依赖 [uv](https://docs.astral.sh/uv/) 管理 Python 环境和命令：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 本地运行

日常开发可以直接使用 `uv run app`：

```bash
uv sync
cp .env.example .env
uv run app
```

默认服务地址：

```text
http://127.0.0.1:8000
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok","app_name":"Paper Plane X"}
```

OpenAPI 文档：

```text
http://127.0.0.1:8000/docs
```

调试模式：

```bash
uv run debug
```

### Web 控制台

后端会尝试托管已构建的前端 console：

1. `settings.api.console_dist_dir`，默认是 `./data/console`
2. monorepo 中的 `../paper_plane_x_frontend/dist`

本地运行时，如果希望打开 `http://127.0.0.1:8000` 就看到 Web 控制台，先从仓库根目录运行：

```bash
just build-console
```

或在 backend 目录运行：

```bash
just build-console
```

### Docker Compose

从源码构建镜像时，Docker 会在构建阶段打包前端 console，容器启动后自带 Web 控制台：

```bash
docker compose up --build
```

默认访问：

```text
http://127.0.0.1:8000
```

发布镜像会推送到 GHCR：

```text
ghcr.io/<owner>/paper-plane-x-backend:<version>
ghcr.io/<owner>/paper-plane-x-backend:latest
```

如果使用已发布镜像，可以设置 `GHCR_OWNER` 和可选的 `PPX_VERSION` 后启动：

```bash
GHCR_OWNER=<owner> PPX_VERSION=0.1.0 docker compose -f docker-compose.release.yml up
```

## 首次配置

LLM Provider 和 Agent LLM 绑定是运行时设置。推荐在前端 Settings 页面配置。

也可以通过 API 配置：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/settings/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "default",
    "model": "deepseek-chat",
    "api_key": "sk-xxx",
    "base_url": "https://api.deepseek.com/v1"
  }'
```

绑定 Agent：

```bash
for agent in extraction analysis fact_check deep_diver query_builder global_finder; do
  curl -s -X PUT "http://127.0.0.1:8000/api/v1/settings/agent_llm/${agent}" \
    -H "Content-Type: application/json" \
    -d '{"provider_name":"default"}'
done
```

需要完整处理 PDF 时，还要配置 PDF Parser。默认配置面向本地 [MinerU](https://opendatalab.github.io/MinerU/) 服务；如果使用云端 MinerU，请在 Settings 页面或 Settings API 中切换。MinerU 源码见 [opendatalab/MinerU](https://github.com/opendatalab/MinerU)。

## 配置和数据目录

| 层           | 来源                                     | 内容                                                         | 生效方式       |
| ------------ | ---------------------------------------- | ------------------------------------------------------------ | -------------- |
| ServerConfig | `.env`、环境变量、`PPX_CONFIG_FILE` TOML | host、port、data_dir、database_path、日志、console 目录      | 修改后重启     |
| AppSettings  | Settings API / 前端 Settings 页面        | LLM Provider、Agent LLM、PDF Parser、Data Process、Librarian | 运行时即时生效 |

默认数据目录：

```text
paper_plane_x_backend/data/
```

常见内容：

- `app.db`：SQLite 数据库。
- `papers/`：PDF 解析产物和图片。
- `project_files/`：项目文件沙箱。
- `logs/`：后端日志。
- `console/`：可选的前端构建产物。

## API 模块

所有业务 API 默认挂在 `/api/v1`。

**Project**

- `POST /projects`
- `GET /projects`
- `GET /projects/{project_id}`
- `PATCH /projects/{project_id}`
- `DELETE /projects/{project_id}`
- `POST /projects/{project_id}/papers/{paper_id}`
- `DELETE /projects/{project_id}/papers/{paper_id}`
- `POST /projects/{project_id}/export`

**Project files**

- `GET /projects/{project_id}/files`
- `GET /projects/{project_id}/files/content`
- `PUT /projects/{project_id}/files/content`
- `POST /projects/{project_id}/files/upload`
- `PATCH /projects/{project_id}/files/lines`
- `PATCH /projects/{project_id}/files/text`
- `PATCH /projects/{project_id}/files/patch`
- `POST /projects/{project_id}/files/export`

**Paper**

- `POST /papers`
- `GET /papers/{paper_id}`
- `PATCH /papers/{paper_id}`
- `DELETE /papers/{paper_id}`
- `GET /papers/{paper_id}/markdown`
- `POST /papers/{paper_id}/reprocess`
- `GET/PUT/PATCH/DELETE /papers/{paper_id}/agent-note`

**Librarian**

- `POST /librarian/global-finder`
- `POST /librarian/global-finder/agent-summary`
- `POST /librarian/search`
- `POST /librarian/matrix`
- `POST /librarian/deep-dive`
- `POST /librarian/query-builder`

**Data Process**

- `GET /data-process/tasks`
- `GET /data-process/tasks/{task_id}`
- `POST /data-process/tasks/{task_id}/cancel`
- `WS /ws/data-process`

**Settings**

- `GET/POST /settings/providers`
- `GET/PUT /settings/agent_llm/{agent}`
- `GET /settings/pdf-parser`
- `PUT /settings/pdf-parser/local`
- `PUT /settings/pdf-parser/cloud`
- `GET/PUT /settings/data-process`
- `GET/PUT /settings/librarian`

**Agent traces**

- `POST /agent-traces/list`
- `POST /agent-traces/query`
- `DELETE /agent-traces/{trace_id}`

## 让后端托管前端

在前端目录构建 console：

```bash
cd ../paper_plane_x_frontend
pnpm build:console
```

然后访问：

```text
http://127.0.0.1:8000
```

后端会渲染 `index.html` 并注入正确的 API base URL。

## ppx CLI 和外部 Agent

`ppx` CLI 位于兄弟包 `../paper_plane_x_cli`，适合脚本和外部 Agent 使用：

```bash
uvx --from ../paper_plane_x_cli ppx --help
uv tool install ../paper_plane_x_cli
```

常用命令：

```bash
ppx context set --base-url http://127.0.0.1:8000/api/v1 --project-id prj_x
ppx project global-finder
ppx librarian search --query-expr "(meta.title CONTAINS transformer)"
ppx librarian matrix --paper-ids pap_a,pap_b --field-paths meta.title,quick_scan.quick_summary
ppx paper markdown --paper-id pap_x --save-dir ./paper-markdown
ppx files upload --source ./notes.md --path /notes/notes.md
```

外部 Agent 可使用 `paper_plane_x_cli/skills/ppx-researcher` 和 `paper_plane_x_cli/skills/ppx-pdf-to-markdown`。

## 常用开发命令

推荐使用 `just`：

```bash
just dev
just test
just lint
just typecheck
just build
just pre-commit
```

等价原始命令：

```bash
uv run app
uv run pytest
uv run ruff check src tests
uv run pyright
uv build
```

## 更多文档

- [Backend Quickstart](docs/workflow_quickstart.md)
- [Architecture](docs/architecture.md)
- [Librarian](docs/librarian.md)
- [Logging](docs/logging_conventions.md)
- [Roadmap](docs/roadmap.md)

## License

Paper Plane X Backend 使用 [GNU Affero General Public License v3.0 or later](LICENSE)。
