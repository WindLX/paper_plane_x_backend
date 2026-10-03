# MinerU 4 本地部署与接口迁移

PPX 0.2.0 的本地解析器要求 MinerU 4.x V1 API。`base_url` 配置为解析服务的基础地址，不含 `/v1`；`output_dir` 是 PPX 本机保存产物的位置。云端 MinerU 解析器继续使用自身云端协议。

后端依次创建 `/v1/uploads`、按返回的 PUT 地址上传原始 PDF、完成上传、提交 `/v1/parse/jobs`，轮询任务状态，下载 `/v1/files/{id}/content`。文件校验和命中时复用已上传文件。请求使用 `standard`、`ocr_mode=auto`、`page_range=all`，下载自包含 ZIP 并读取其中的 `markdown.md` 与引用图片，避免单独 Markdown 下载内嵌 base64 图片。失败、取消、部分成功、非法响应和缺失产物均返回解析错误。

PPX 对外接口仍是 `POST /api/v1/parse/pdf`，返回 `md_content`、base64 `images` 和 `parser_type`。CLI 保持原有 JSON 字段，新增 `ppx pdf parse --timeout`，默认 1800 秒，涵盖首次模型加载与解析。后端任务等待也限制为 1800 秒；客户端超时不取消远端任务，检查日志中的 job_id 后再决定重试。

## 按需部署

部署模板位于 [`../ops/mineru/`](../ops/mineru/)。部署前调整模板中的路径和 GPU 编号，使用 MinerU 4.0.10 的独立环境安装 `mineru[full]==4.0.10`，下载并校验匹配的 torch + vLLM standard 模型。模板网关依赖 `aiohttp`；MinerU 环境包含该依赖。

- API 在回环地址 17860 端口，WebUI 在回环地址 17861 端口。
- `mineru-gateway.service` 在 7860 和 7861 端口常驻，访问时启动对应 worker；WebUI 访问先启动 API。
- API/WebUI 服务保持 disabled，由网关按需启动；只启用网关开机启动。
- 最后一次有效请求结束或后台任务被观察为运行后，闲置超过 3600 秒，网关检查任务列表再停止两个 worker。检查每 30 秒进行一次，实际停止可能晚于阈值约 30 秒。
- 上传、下载和 WebUI 提交过程受到保护，queued/running 的 API 任务阻止停止；Gradio 的 heartbeat/SSE 保活不会永久占用 GPU。
- 网关持有启动/停止锁，避免新请求与闲置停止同时操作 worker；首次启动最多等待 600 秒。

日常管理：

```bash
systemctl status mineru-gateway mineru-api mineru-web
journalctl -u mineru-api -u mineru-gateway -f
systemctl stop mineru-web mineru-api
```

手动停止后，下次访问仍会唤醒。维护时先停止网关，避免访问重新启动 worker。模型加载惰性进行，API 就绪不代表 GPU 模型已加载。

MinerU V1 的 upload/file/job 资源索引存在进程内存中，worker 停止后旧资源 ID 失效。PPX 下载完成后保留本机产物；长时间中断的外部 V1 客户端应重新上传并创建任务。此部署面向可信局域网；外网部署另行配置认证和网络访问控制。

## English migration notes

PPX 0.2.0 requires MinerU 4.x V1 for local parsing. Set the base URL without `/v1`. PPX uploads the PDF, submits a Standard-tier job covering all pages, polls it, and downloads Markdown plus referenced images. The public PPX PDF endpoint and CLI JSON fields remain stable. `ppx pdf parse --timeout` defaults to 1800 seconds, including cold startup; timing out does not cancel remote work.

The lightweight gateway keeps the public API/WebUI ports available while GPU workers are stopped. It starts workers on demand and stops both after more than one idle hour, checking every 30 seconds. Active transfers and queued/running jobs prevent shutdown; UI heartbeat traffic does not keep GPU workers alive. MinerU resource IDs expire across worker restarts, so clients should finish downloading outputs promptly.
