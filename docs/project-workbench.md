# 后端项目工作台

后端拥有项目工作台的全部数据：只读的项目总览、项目拥有的持久活动历史、识别图片的项目文件沙箱，以及后台运行的 ZIP 导出作业。本文记录这些能力的契约与持久化边界；完整请求/响应模型以运行中服务的 `/docs` 为准，不在本文复制接口清单。

## 路由分组

| 能力 | 路径前缀 | 说明 |
| ---- | -------- | ---- |
| 概览 | `GET /projects/{id}/overview` | 只读聚合，不调用模型 |
| 活动 | `GET /projects/{id}/activities` | 过滤与分页查询活动历史 |
| 导出作业 | `/projects/{id}/exports` | 提交、列表、查询、取消、下载 |
| 项目文件 | `/projects/{id}/files` | list/read/write/patch/upload/export |
| 图片文件 | `GET /files/download`、`GET /files/preview` | 原始字节下载与内联预览 |

现有客户端仍可使用同步导出 API `POST /projects/{id}/export`；Web 控制台使用后台导出作业端点，两者复用同一套打包逻辑。

## 概览聚合

`ProjectOverviewService.build` 组合论文数、已解析数、进行中任务数、需要关注条数、最近论文（最多 5 条）、最近沙箱文件（最多 5 条）、最近活动（最多 5 条）、热门标签和年份分布。它只读现有表与检索统计，**不触发任何模型调用**。

最近文件、近期活动和辅助统计按区块返回 `section_errors`，其余区块照常展示；核心项目或数据库读取失败则返回请求错误。`agent_summary` 只在这里读取；生成或覆盖摘要由显式写端点完成。

需要关注的条目按阶段代码区分任务失败、解析失败与事实核查失败，并给出关联任务 ID 与错误信息。

## 活动历史

活动存放在 `project_activities` 表，由项目拥有，独立于旧的 `projects.operation_logs` JSON 列和数据处理任务表。写入时快照类别、事件、状态、时间与错误，读取时不回连任务表：因此任务记录删除、论文与项目解除关联之后，活动仍然保留，并通过 `task_exists` 表示关联任务是否仍然存在。

实时写入与 `operation_logs` 迁移共用确定性 ID（`uuid5` 种子），保证同一事件不会被记录两次。迁移只回填已知的 operation 代码，未识别的代码不会被伪造成活动。

删除任务、删除论文或解除项目关联都**不得**级联删除活动行；活动随项目生命周期单独清理。查询支持按类别、状态、创建时间范围与关键词过滤，并按时间倒序分页。

归属与持久化的取舍见顶层 [ADR 0001](../../docs/adr/0001-project-activity-history.md)。

## 项目文件：图片、校验与下载

沙箱允许文本扩展名（`.md`、`.txt`、`.json`、`.csv`、`.yaml`、`.yml`、`.toml`）与图片扩展名（`.png`、`.jpg`、`.jpeg`、`.webp`、`.gif`、`.svg`），单文件上限为 10 MiB。

上传按真实内容校验而不是只看扩展名：先按文件头识别类型，再要求与扩展名一致，并用 Pillow 解码校验位图。SVG 必须是静态自包含文档——拒绝 `<script>`、动画元素、`<foreignObject>`、`on*` 事件属性、外部 `href`/`url()` 引用、`@import`、DTD、实体和处理指令。文本文件按原样保存；图片校验通过后原样落盘。

图片与文本都支持原字节下载：`GET /files/download` 不解码，按磁盘原始字节返回，并复用沙箱的路径、扩展名与大小校验。`GET /files/preview` 仅接受图片，按真实内容返回 MIME，带 `Content-Security-Policy: sandbox` 与 `X-Content-Type-Options: nosniff`，即使直接打开 SVG 也无法执行脚本。

就地编辑只针对文本：write、replace-lines、replace-text 与 patch 都不接受图片扩展名。

## Markdown 导出的图片引用

导出 Markdown 为 DOCX/PDF/HTML 时，先解析正文中的图片引用（markdown-it 解析 Markdown，HTMLParser 解析 `<img>`），再做 preflight：

- 以 `/` 开头的引用相对项目根解析；其余引用相对被导出 Markdown 所在目录解析；`..` 允许使用，但解析结果必须仍在项目根内，越界会报 `path_escapes_sandbox`。
- 带协议（`http`、`https`、`file` 等）或协议相对的引用视为外部资源并直接报错，导出过程**不会**联网抓取。
- `data:` 自包含引用保持原样。
- 引用必须是沙箱内已存在、非符号链接、大小合规且通过图片校验的图片。

preflight 失败时以 `export_invalid_resources` 返回逐条原因，不产生半成品。DOCX/PDF 导出把 Pandoc 渲染不一致的格式转换为 PNG：WebP 与 GIF 取首帧，SVG 通过 `rsvg-convert` 以 3 倍比例栅格化；HTML 导出把图片资源内嵌进文档。

## 导出作业

导出作业独立于论文处理任务，由 `ProjectExportManager` 在应用 lifespan 中启动。约束与语义：

- 单个 worker 串行处理；同一项目已有 `queued`/`running` 任务时再次提交返回 409。
- 阶段为 `queued` → `preparing` → `packing` → `finalizing` → `ready`，`total_files` 是真实归档条目数（包含元数据 JSON），`processed_files` 随实际写入递增。
- 取消：`queued` 任务立即转为 `canceled`；`running` 任务置 `cancel_requested`，worker 在下一次检查点停止并清理半成品。
- 完成后保留 24 小时，随后标记 `expired` 并删除产物；对未完成任务下载返回 409，对过期或产物缺失返回 410。
- 重启：启动时把遗留的 `queued`/`running` 任务标记为 `failed`，删除 `.partial` 文件，**不自动恢复**，需要重新发起。

导出打包本身在 `ProjectOrchestrator.export_project_bundle` 中流式写 ZIP，并在分块之间检查取消，避免大文件锁死取消。

## 依赖

图片处理依赖 `Pillow`（位图解码）、`defusedxml`（安全 XML 解析）、`tinycss2`（SVG 内嵌 CSS 资源引用校验）与 `markdown-it-py`（图片引用解析）；SVG 栅格化依赖随镜像安装的 `rsvg-convert`（Debian `librsvg2-bin`）。缺少 `rsvg-convert` 时导出 SVG 会返回可定位的错误。

DOCX/HTML 转换需要 Pandoc；PDF 另需可用的 PDF engine（例如 Typst 或 XeLaTeX），在设置页面配置路径。容器安装 `librsvg2-bin` 只解决 SVG 栅格化依赖，不替代 Pandoc 和 PDF engine。转换只向转换器提供已校验的受控资源目录，不把完整项目目录设为资源路径。

## 验证

在 backend 内运行 `just test tests/unit/test_project_images.py tests/unit/test_project_export_conversion.py tests/unit/test_project_exports.py tests/unit/test_project_activity.py tests/unit/test_project_overview.py tests/integration/test_project_exports_api.py tests/integration/test_project_workbench_api.py`，再运行 `just pre-commit`。真实带图转换用例需要上述系统工具；缺少工具时会明确跳过，不能据此声称完成 PDF 版面验收。
