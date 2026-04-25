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

## 9. 成功验收标准

如果下面这些都成立，说明后端主链路基本可用：

1. 健康检查返回 200
2. 可以创建项目
3. 上传 PDF 后可以拿到 `task_id`
4. 任务能进入 `QUEUED/RUNNING/COMPLETED/FAILED` 之一
5. `GET /api/v1/papers/{paper_id}` 能返回论文记录
6. `raw_pdf_path` 落到了本地数据目录

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
