# Paper Plane X Backend

FastAPI 应用。PDF 解析、结构化分析、文献检索、ResearcherAgent 对话。

## 启动

```bash
uv sync && cp .env.example .env && uv run app
```

`http://127.0.0.1:8000`

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","app_name":"Paper Plane X"}
```

调试模式：

```bash
uv run debug
```

## 首次配置

LLM Provider 和 Agent LLM 绑定不在 `.env` 里。可以在前端 Settings 页面操作。

也通过 Settings API 配置：

```bash
# 创建 Provider
curl -s -X POST http://127.0.0.1:8000/api/v1/settings/providers \
  -H "Content-Type: application/json" \
  -d '{"name":"default","model":"deepseek-chat","api_key":"sk-xxx","base_url":"https://api.deepseek.com/v1"}'

# 绑定所有 Agent 到此 Provider
for agent in extraction analysis fact_check deep_diver query_builder global_finder researcher; do
  curl -s -X PUT "http://127.0.0.1:8000/api/v1/settings/agent-llm/${agent}" \
    -H "Content-Type: application/json" \
    -d '{"provider_name":"default"}'
done
```


## 配置分层

| 层           | 来源                            | 内容                                          | 修改           |
| ------------ | ------------------------------- | --------------------------------------------- | -------------- |
| ServerConfig | `.env` / `PPX_CONFIG_FILE` TOML | host, port, log, data_dir                     | 改文件重启     |
| AppSettings  | Settings API                    | LLM Provider, Agent LLM, MinerU, Data Process | 运行时即时生效 |

## API

全部挂在 `/api/v1`。完整 OpenAPI：`http://127.0.0.1:8000/docs`

**Project**
- `POST /projects`, `GET /projects`, `GET/PATCH/DELETE /projects/{id}`
- `POST /projects/{id}/papers/{paper_id}` — 关联论文
- `POST /projects/{id}/search`
- `POST /projects/{id}/export`

**Paper**
- `POST /papers` — 上传 PDF
- `GET /papers/{id}`, `PATCH /papers/{id}`, `DELETE /papers/{id}`
- `GET /papers/{id}/markdown` — 下载解析后的完整 Markdown
- `POST /papers/{id}/reprocess`

**Librarian**
- `POST /librarian/search` — DSL 检索
- `POST /librarian/matrix` — 批量拉取结构化字段
- `POST /librarian/deep-dive` — 单篇问答
- `POST /librarian/global-finder` — 项目总览
- `POST /librarian/query-builder` — 自然语言转 DSL

**Conversation**
- `POST /conversations`
- `WS /ws/conversations/{id}` — 流式对话

**Data Process**
- `GET /data-process/tasks`
- `POST /data-process/tasks/{id}/cancel`
- `WS /ws/data-process` — 实时任务事件

**Settings**
- `GET/POST /settings/providers`
- `GET/PUT /settings/agent-llm/{agent}`
- `GET/PUT /settings/mineru`, `GET/PUT /settings/data-process`, `GET/PUT /settings/librarian`

## ppx CLI

`ppx` 已拆到兄弟包 `../paper_plane_x_cli`，通过 HTTP 调用本服务。一次性运行或全局安装：

```bash
uvx --from ../paper_plane_x_cli ppx --help
uv tool install ../paper_plane_x_cli
```

安装后：

```bash
ppx context set --base-url http://127.0.0.1:8000/api/v1 --project-id prj_x
ppx project global-finder
ppx librarian search --query-expr "(meta.title CONTAINS transformer)"
ppx paper markdown --paper-id pap_x --save-dir ./paper-markdown
ppx files list --dir /
ppx files upload --source ./notes.md --path /notes/notes.md
```

## 开发

```bash
uv run app                 # 启动
./scripts/test.sh          # 全量测试
uv run ruff check .        # Lint
uv run pyright             # Type check
```

## 文档

- [Quickstart](docs/workflow_quickstart.md)
- [Architecture](docs/architecture.md)
- [Librarian](docs/librarian.md)
- [Logging](docs/logging_conventions.md)
- [Roadmap](docs/roadmap.md)
