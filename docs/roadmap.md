# Paper Plane X Backend Roadmap

更新时间：2026-07-08

这份文档记录当前真实状态和下一步优先级。它不是历史设计稿。

## 当前状态快照

后端当前已经具备可用的科研文献工作流：

- Project / Paper CRUD 与项目-论文关联。
- PDF 上传、异步 Data Process、任务持久化、取消、重试、删除。
- Extraction / Analysis / Fact Check 结构化处理链。
- Paper detail、人工回填、paper note。
- Librarian search / matrix / deep-dive / global-finder / query-builder。
- Project file sandbox：list/read/write/delete/export/find/lines/replace/patch。
- Agent trace 查询与列表。
- Settings API。
- 后端托管已构建 Web console。
- Docker image 发布链路。
- 兄弟包 `paper_plane_x_cli` 中的 `ppx` HTTP CLI。
- `paper_plane_x_cli/skills/ppx-researcher` 与 `ppx-pdf-to-markdown` 外部 Agent skill。

已移除：

- 内置 Conversation REST / WebSocket。
- 内置 ResearcherAgent。
- HITL WebSocket 与 `ask_human`。
- 旧 conversation 表会在启动迁移时完整备份后删除。

## 已完成阶段

### Phase 1: 后端基础骨架

| 能力                                 | 状态   |
| ------------------------------------ | ------ |
| FastAPI app、配置系统、uv 项目结构   | 已完成 |
| SQLite 封装、schema 初始化、迁移兼容 | 已完成 |
| Project / Paper 数据模型             | 已完成 |
| Project API                          | 已完成 |
| 单元/集成测试基础                    | 已完成 |

### Phase 2: Agent Runtime

| 能力                                         | 状态   |
| -------------------------------------------- | ------ |
| LiteLLM client                               | 已完成 |
| Memory 与 OpenAI-compatible message schema   | 已完成 |
| ToolRegistry 与 `@tool`                      | 已完成 |
| `runtime_context` hidden parameter injection | 已完成 |
| BaseAgent normal 模式与 trace 落库           | 已完成 |
| structured output 校验                       | 已完成 |

### Phase 3: Data Process

| 能力                               | 状态   |
| ---------------------------------- | ------ |
| PDF 上传与 paper 创建/复用         | 已完成 |
| 本地 / 云端 PDF Parser             | 已完成 |
| Extraction / Analysis / Fact Check | 已完成 |
| task manager、worker pool、持久化  | 已完成 |
| cancel / retry / delete task       | 已完成 |
| paper reprocess                    | 已完成 |
| 人工回填                           | 已完成 |

### Phase 4: Librarian 与项目资产

| 能力                                        | 状态   |
| ------------------------------------------- | ------ |
| `POST /api/v1/librarian/search`             | 已完成 |
| `POST /api/v1/librarian/matrix`             | 已完成 |
| `POST /api/v1/librarian/deep-dive`          | 已完成 |
| `POST /api/v1/librarian/global-finder`      | 已完成 |
| `POST /api/v1/librarian/query-builder`      | 已完成 |
| `POST /api/v1/projects/{project_id}/search` | 已完成 |
| Project file sandbox API                    | 已完成 |
| Paper note API                              | 已完成 |

### Phase 5: External Agent Integration

| 能力                                                               | 状态   |
| ------------------------------------------------------------------ | ------ |
| `ppx` HTTP CLI                                                     | 已完成 |
| CLI context：flag > env > local context > global context > default | 已完成 |
| CLI commands：librarian / files / paper / paper-note / context     | 已完成 |
| `ppx-researcher` skill                                             | 已完成 |
| `ppx-pdf-to-markdown` skill                                        | 已完成 |

### Phase 6: Deployment

| 能力                              | 状态   |
| --------------------------------- | ------ |
| Backend-hosted console            | 已完成 |
| Docker image with bundled console | 已完成 |
| GitHub Actions CI                 | 已完成 |
| Tag release workflow              | 已完成 |
| CLI PyPI publish workflow         | 已完成 |

## 当前优先级

### P0: 文档和使用体验

- 保持 README、quickstart、architecture、librarian、skill 同步。
- 持续清理已删除 Conversation / ResearcherAgent / HITL 的残留说明。
- 为 `ppx` 增加更友好的 `--help` 示例或 docs 生成。

### P1: 处理链稳定性

- 改善 DeepDiver 失败诊断与重试体验。
- 强化 PDF Parser 错误提示。
- 补充更多真实 PDF 样例的回归测试。

### P2: 部署与生态

- 发布后的 GHCR / PyPI / Zotero XPI 验证流程。
- 补充生产配置样例。
- 补充 Docker Compose 用户模板。

## 维护原则

1. 新 API 必须有 integration test。
2. 新 tool 必须同步更新 skill、tool-guide。
3. 修改 CLI 命令必须同步更新 README、quickstart、librarian docs。
4. 修改数据库 schema 必须包含迁移和测试。
5. 文档只描述当前真实实现；历史设计和废弃接口不要保留在主文档正文。

## TODO

- [x] 文件沙箱系统优化和 bug 修复
- [x] export 支持导出沙箱文件
- [x] MinerU / PDF Parser API
- [x] 优化 skills
- [x] 删除内置 Conversation / ResearcherAgent / HITL
- [x] 优化 Docker 部署
- [x] 优化用户向 README
- [x] 优化 CI/CD
- [x] Fetch paper context
- [x] 修复 Deep Diver API 的问题
- [x] 修复 Pandoc 多格式导出问题
- [ ] 修复前端锁定浏览器的 bug
- [x] 修复前端 json 无法复制的问题
- [x] Agent 备注可编辑
- [ ] External Editor
- [x] Agent 缓存优化
- [ ] 优化前端项目页面展示
- [x] zotero 批量刷新
- [x] task 搜索 paper id 搜索不到的问题
- [x] 前端搜索页面提示
- [x] 前端搜索页面支持直接输入 paper id
- [x] 添加 pdf 下载 api
- [x] 前端支持阅读 pdf