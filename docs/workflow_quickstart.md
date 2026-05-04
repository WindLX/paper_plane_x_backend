# Backend Quickstart

这份文档用于快速验证后端是否真的能工作。目标不是覆盖所有功能，而是用最短路径确认：

1. 服务能启动
2. 项目能创建
3. PDF 能上传并进入任务队列
4. 能查看任务和论文结果

## 1. 前置条件

- 已在仓库根目录或 `paper_plane_x_backend/` 目录
- Python 与 `uv` 可用
- 后端依赖已安装
- 如需完整跑通处理链，MinerU 与 LLM 配置可用

## 2. 启动服务

```bash
cd paper_plane_x_backend
uv sync
cp .env.example .env
./scripts/dev_api.sh
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok","app_name":"Paper Plane X"}
```

## 3. 创建项目

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Quickstart Project","description":"backend smoke test"}'
```

保存返回里的 `project_id`：

```bash
export PROJECT_ID="replace-with-project-id"
```

## 4. 上传 PDF

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
- 返回状态说明

提取环境变量：

```bash
export PAPER_ID="$(jq -r '.resource_id // .paper_id' /tmp/ppx_start_resp.json)"
export TASK_ID="$(jq -r '.task_id' /tmp/ppx_start_resp.json)"
```

## 5. 关联到项目

上传不会自动关联到指定项目，如需放入项目中，需要显式调用：

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/papers/${PAPER_ID}"
```

## 6. 查看任务状态

列出任务：

```bash
curl -s "http://127.0.0.1:8000/api/v1/data-process/tasks"
```

查看单个任务：

```bash
curl -s "http://127.0.0.1:8000/api/v1/data-process/tasks/${TASK_ID}"
```

重点字段：

- `status`
- `error`
- `retry_of_task_id`
- `started_at`
- `finished_at`

## 7. 查看论文详情

```bash
curl -s "http://127.0.0.1:8000/api/v1/papers/${PAPER_ID}"
```

建议重点看：

- `extraction_status`
- `extraction_fact_check_status`
- `analysis_fact_check_status`
- `raw_pdf_path`
- `quick_scan`
- `synthesis_data`
- `analysis_report`

## 8. 常见操作

### 8.1 取消任务

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/data-process/tasks/${TASK_ID}/cancel"
```

### 8.2 重试任务

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/data-process/tasks/${TASK_ID}/retry"
```

### 8.3 重跑指定论文

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/papers/${PAPER_ID}/reprocess" \
  -F "pdf_file=@${PDF_PATH};type=application/pdf"
```

### 8.4 查看项目内论文

```bash
curl -s "http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/papers"
```

## 9. Conversation 流式对话快速验证

### 9.1 创建对话

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/conversations \
  -H "Content-Type: application/json" \
  -d "{\"project_id\":\"${PROJECT_ID}\",\"title\":\"Test Chat\"}"
```

保存返回中的 `conversation_id`：

```bash
export CONV_ID="replace-with-conversation-id"
```

### 9.2 WebSocket 流式对话

使用 `websocat` 或浏览器开发者工具连接：

```bash
websocat "ws://127.0.0.1:8000/api/v1/ws/conversations/${CONV_ID}"
```

发送用户消息：

```json
{"type":"user_message","content":"请帮我搜索项目中关于深度学习的论文"}
```

期望收到：

```json
{"type":"stream_start","message_id":"msg-xxx"}
{"type":"stream_chunk","delta":"...","reasoning_delta":"...","step":1}
{"type":"tool_call","name":"search_paper","step":1}
{"type":"stream_complete","message_id":"msg-xxx","trace_ids":["trc-xxx"]}
```

### 9.3 查看对话历史

```bash
curl -s "http://127.0.0.1:8000/api/v1/conversations/${CONV_ID}/messages"
```

## 10. HITL 人机交互快速验证

### 10.1 连接 HITL WebSocket

```bash
websocat "ws://127.0.0.1:8000/api/v1/ws/hitl"
```

### 10.2 触发 ask_human（通过对话）

在 conversation WebSocket 中发送：

```json
{"type":"user_message","content":"请帮我总结这些论文，但先问一下我应该关注哪个方向"}
```

如果 ResearcherAgent 决定调用 `ask_human`，HITL WebSocket 会收到：

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

### 10.3 提交回答

在 HITL WebSocket 中发送：

```json
{
  "type": "answer",
  "question_id": "hit-xxx",
  "answers": [
    {"question_index": 0, "selected_option_ids": ["opt-1"], "custom_text": ""}
  ]
}
```

期望收到确认：

```json
{"type":"hitl_answered","question_id":"hit-xxx"}
```

Agent 随后会继续执行并返回结果。

## 11. 成功验收标准

如果下面这些都成立，说明后端主链路基本可用：

1. 健康检查返回 200
2. 可以创建项目
3. 上传 PDF 后可以拿到 `task_id`
4. 任务能进入 `QUEUED/RUNNING/COMPLETED/FAILED` 之一
5. `GET /api/v1/papers/{paper_id}` 能返回论文记录
6. `raw_pdf_path` 落到了本地数据目录
7. 可以创建 conversation 并通过 WebSocket 进行流式对话
8. HITL WebSocket 能接收和响应问题（当 Agent 调用 `ask_human` 时）

## 10. 常见问题

### 上传成功但任务最后失败

优先检查：

- MinerU 是否可访问
- LLM API key 是否正确
- 后端日志是否有具体报错

### 一直停留在 `QUEUED`

优先检查：

- worker pool 是否正常启动
- `data_process.worker_count` 是否大于 0

### 没看到 console

后端只会托管已经构建好的前端静态资源。若未构建 console，根路径不会自动出现前端页面。
