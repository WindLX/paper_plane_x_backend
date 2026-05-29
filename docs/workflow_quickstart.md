# Backend Quickstart

这份文档用于快速验证 Paper Plane X Backend 是否能工作。目标是让用户和开发者能复制命令完成一条最小闭环：

1. 启动服务
2. 创建项目
3. 上传并处理论文
4. 关联项目
5. 查询结果
6. 用 Librarian / `ppx` 做项目级研究操作
7. 可选验证 Conversation 和 HITL

## 1. 前置条件

- Python 3.12+
- `uv`
- 本地 SQLite 可用
- 如需完整处理 PDF：MinerU 可用，且后端已配置 LLM Provider（见第 3 步）
- 可选：`jq`、`websocat`

## 2. 启动服务

```bash
cd paper_plane_x_backend
uv sync
cp .env.example .env
uv run app
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
```

期望：

```json
{"status":"ok","app_name":"Paper Plane X"}
```

OpenAPI 文档：

```text
http://127.0.0.1:8000/docs
```

## 3. 首次配置 LLM Provider

上传和处理论文需要 LLM。Provider 不在 `.env` 中配置，而是通过 Settings API 管理。

创建第一个 Provider（以 deepseek 为例）：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/settings/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "default",
    "model": "deepseek-chat",
    "api_key": "your-api-key",
    "base_url": "https://api.deepseek.com/v1"
  }'
```

然后把每个 Agent 绑定到这个 Provider：

```bash
for agent in extraction analysis fact_check deep_diver query_builder global_finder researcher subagent; do
  curl -s -X PUT "http://127.0.0.1:8000/api/v1/settings/agent-llm/${agent}" \
    -H "Content-Type: application/json" \
    -d '{"provider_name": "default"}'
done
```

也可以用控制台 UI（`http://127.0.0.1:8000`）在 Settings 页面图形化配置。

## 4. 创建项目

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Quickstart Project","description":"backend smoke test"}'
```

保存返回里的 `project_id`：

```bash
export PROJECT_ID="replace-with-project-id"
```

## 5. 上传 PDF

```bash
export PDF_PATH="/absolute/path/to/your/test.pdf"
```

```bash
curl -s -o /tmp/ppx_start_resp.json -w "%{http_code}\n" \
  -X POST "http://127.0.0.1:8000/api/v1/papers" \
  -F "pdf_file=@${PDF_PATH};type=application/pdf" \
  -F "title=Quickstart Paper" \
  -F "authors=Alice,Bob" \
  -F "year=2024" \
  -F "publication=ArXiv"
```

查看返回：

```bash
cat /tmp/ppx_start_resp.json
```

期望：

- HTTP 状态码通常为 `202`
- 返回 `paper_id` 或 `resource_id`
- 返回 `task_id`

提取变量：

```bash
export PAPER_ID="$(jq -r '.resource_id // .paper_id' /tmp/ppx_start_resp.json)"
export TASK_ID="$(jq -r '.task_id' /tmp/ppx_start_resp.json)"
```

## 6. 关联论文到项目

上传论文不会自动绑定项目。显式关联：

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/papers/${PAPER_ID}"
```

## 7. 查看任务和论文

列出任务：

```bash
curl -s "http://127.0.0.1:8000/api/v1/data-process/tasks"
```

查看单个任务：

```bash
curl -s "http://127.0.0.1:8000/api/v1/data-process/tasks/${TASK_ID}"
```

查看论文详情：

```bash
curl -s "http://127.0.0.1:8000/api/v1/papers/${PAPER_ID}"
```

重点字段：

- `extraction_status`
- `extraction_fact_check_status`
- `analysis_fact_check_status`
- `quick_scan`
- `synthesis_data`
- `analysis_report`
- `agent_note`

## 8. Librarian API 快速验证

### 7.1 项目级总览

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/librarian/global-finder \
  -H "Content-Type: application/json" \
  -d "{\"project_id\":\"${PROJECT_ID}\"}"
```

### 7.2 搜索项目论文

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/librarian/search \
  -H "Content-Type: application/json" \
  -d "{
    \"project_id\":\"${PROJECT_ID}\",
    \"query_expr\":\"(quick_scan.tags CONTAINS 强化学习)\",
    \"limit\":10,
    \"offset\":0
  }"
```

### 7.3 矩阵读取结构化字段

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/librarian/matrix \
  -H "Content-Type: application/json" \
  -d "{
    \"paper_ids\":[\"${PAPER_ID}\"],
    \"field_paths\":[
      \"meta.title\",
      \"quick_scan.quick_summary\",
      \"synthesis_data.methodology.innovation.text\"
    ]
  }"
```

### 7.4 单篇论文 deep dive

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/librarian/deep-dive \
  -H "Content-Type: application/json" \
  -d "{
    \"paper_id\":\"${PAPER_ID}\",
    \"question\":\"这篇论文的核心创新是什么？请简短回答。\"
  }"
```

## 9. `ppx` CLI 快速验证

`ppx` 是外部 agent 和脚本的推荐入口。它调用 HTTP API，并输出 JSON。

```bash
uvx --from ../paper_plane_x_cli ppx --help
uv tool install ../paper_plane_x_cli

ppx context set \
  --base-url http://127.0.0.1:8000/api/v1 \
  --project-id "$PROJECT_ID"

ppx context show
ppx project global-finder
```

常用命令：

```bash
ppx librarian search \
  --query-expr "(quick_scan.tags CONTAINS 强化学习)" \
  --limit 10

ppx librarian matrix \
  --paper-ids "$PAPER_ID" \
  --field-paths meta.title,quick_scan.verdict,quick_scan.quick_summary

ppx librarian deep-dive \
  --paper-id "$PAPER_ID" \
  --question "这篇论文解决什么问题？"
```

## 10. 项目文件和论文笔记

### 9.1 Project files

```bash
ppx files list --dir /
ppx files write --path /notes/quickstart.md --content "# Quickstart Notes"
printf "# Local Notes\n" > /tmp/ppx-local-notes.md
ppx files upload --source /tmp/ppx-local-notes.md --path /notes/local-notes.md
ppx files read --path /notes/quickstart.md
ppx files find --path /notes/quickstart.md --query Quickstart
ppx files lines --path /notes/quickstart.md --start-line 1 --end-line 5
```

小范围编辑：

```bash
ppx files patch \
  --path /notes/quickstart.md \
  --action insert_after \
  --anchor-text "# Quickstart Notes" \
  --content "\n\nValidated with Paper Plane X.\n"
```

### 9.2 Paper note

```bash
ppx paper-note get --paper-id "$PAPER_ID"
ppx paper-note write --paper-id "$PAPER_ID" --content "初步结论：..."
ppx paper-note delete --paper-id "$PAPER_ID"
```

## 11. Conversation 流式对话

创建对话：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/conversations \
  -H "Content-Type: application/json" \
  -d "{\"project_id\":\"${PROJECT_ID}\",\"title\":\"Quickstart Chat\"}"
```

保存：

```bash
export CONV_ID="replace-with-conversation-id"
```

连接 WebSocket：

```bash
websocat "ws://127.0.0.1:8000/api/v1/ws/conversations/${CONV_ID}"
```

发送：

```json
{"type":"user_message","content":"请帮我搜索项目中关于强化学习的论文"}
```

期望收到：

```json
{"type":"stream_start","message_id":"msg-xxx"}
{"type":"stream_chunk","delta":"...","reasoning_delta":"...","step":1}
{"type":"tool_call","name":"search_paper","step":1}
{"type":"stream_complete","message_id":"msg-xxx","trace_ids":["trc-xxx"]}
```

查看历史：

```bash
curl -s "http://127.0.0.1:8000/api/v1/conversations/${CONV_ID}/messages"
```

## 11. HITL 人机交互

连接 HITL WebSocket：

```bash
websocat "ws://127.0.0.1:8000/api/v1/ws/hitl"
```

当 ResearcherAgent 调用 `ask_human`，HITL WebSocket 会收到：

```json
{
  "type": "hitl_question",
  "question_id": "hit-xxx",
  "project_id": "prj-xxx",
  "conversation_id": "cnv-xxx",
  "questions": [
    {
      "text": "您希望关注哪个研究方向？",
      "options": [
        {"id": "opt-1", "text": "方法论创新"},
        {"id": "opt-2", "text": "实验设计"}
      ],
      "allow_multiple": false,
      "custom_answer_label": "其他（请自定义回答）"
    }
  ]
}
```

提交回答：

```json
{
  "type": "answer",
  "question_id": "hit-xxx",
  "answers": [
    {"question_index": 0, "selected_option_ids": ["opt-1"], "custom_text": ""}
  ]
}
```

## 12. 成功验收标准

如果下面这些成立，说明后端主链路可用：

1. Health check 返回 200。
2. 可以创建项目。
3. 上传 PDF 后可以拿到 `task_id`。
4. 任务进入 `QUEUED` / `RUNNING` / `COMPLETED` / `FAILED` 之一。
5. `GET /api/v1/papers/{paper_id}` 返回论文记录。
6. 可以把论文关联到项目。
7. `librarian/search` 或 `ppx librarian search` 返回项目内论文。
8. `ppx files list --dir /` 可以访问项目文件沙箱。
9. Conversation WebSocket 可以流式返回。

## 13. 常见问题

### 上传成功但任务最后失败

优先检查：

- MinerU 是否可访问。
- LLM provider 和 Agent LLM 绑定是否配置。
- 后端日志是否有 `event=data_process.*` 或 `event=agent.*` 错误。

### 一直停留在 `QUEUED`

优先检查：

- worker pool 是否正常启动。
- `data_process.worker_count` 是否大于 0。

### `ppx` 报连接错误

优先检查：

- `ppx context show` 的 `base_url` 是否包含 `/api/v1`。
- 后端是否正在运行。
- 当前机器是否能访问该 host/port。
