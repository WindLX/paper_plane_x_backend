# Paper Plane X Backend Roadmap

更新时间：2026-05-25

这份文档记录当前真实状态和下一步优先级。它不是历史设计稿。

## 当前状态快照

后端当前已经具备完整可用的科研文献工作流：

- Project / Paper CRUD 与项目-论文关联。
- PDF 上传、异步 Data Process、任务持久化、取消、重试、删除。
- Extraction / Analysis / Fact Check 结构化处理链。
- Paper detail、人工回填、paper note。
- Librarian search / matrix / deep-dive / global-finder / query-builder。
- Project file sandbox：list/read/write/delete/export/find/lines/replace/patch。
- ResearcherAgent 项目级 WebSocket 对话。
- HITL WebSocket 与 `ask_human`。
- Agent trace 查询与列表。
- Settings API。
- 兄弟包 `paper_plane_x_cli` 中的 `ppx` HTTP CLI。
- `paper_plane_x_cli/skills/paper-plane-x-researcher` 外部 agent skill。
- 测试基线：`362 passed`。

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
| MinerU 解析                        | 已完成 |
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

### Phase 5: Researcher Workflow

| 能力                             | 状态   |
| -------------------------------- | ------ |
| Conversation REST                | 已完成 |
| Conversation WebSocket streaming | 已完成 |
| ResearcherAgent tools            | 已完成 |
| HITL WebSocket                   | 已完成 |
| `ask_human`                      | 已完成 |

### Phase 6: External Agent Integration

| 能力                                                           | 状态   |
| -------------------------------------------------------------- | ------ |
| `ppx` HTTP CLI                                                 | 已完成 |
| CLI context：flag > env > saved config                         | 已完成 |
| CLI commands：librarian / files / paper-note / context         | 已完成 |
| `paper-plane-x-researcher` skill                               | 已完成 |
| Skill 包含 Researcher 行为、工具说明、field paths、query rules | 已完成 |

## 当前优先级

### P0: 文档和使用体验

- 保持 README、quickstart、architecture、librarian、skill 同步。
- 为外部 agent 安装/复制 skill 的路径补充更明确说明。
- 为 `ppx` 增加更友好的 `--help` 示例或 docs 生成。

### P1: Researcher 工作流增强

- 对长任务和离开页面后的 streaming 恢复做更强支持。
- 优化消息编辑、分支、刷新后的状态一致性。
- 改善 trace 与 conversation 的互相跳转体验。

### P2: 部署与生态

- Docker / compose 文档与生产配置样例加强。

## 维护原则

1. 新 API 必须有 integration test。
2. 新 tool 必须同步更新 Researcher prompt、skill、tool-guide。
3. 修改 CLI 命令必须同步更新 README、quickstart、librarian docs。
4. 修改数据库 schema 必须包含迁移和测试。
5. 文档只描述当前真实实现；历史设计和废弃接口不要保留在主文档正文。

## TODO

- [x] 文件沙箱系统优化和 bug 修复
- [x] export 支持导出沙箱文件
- [x] 前端渲染问题, 左侧边栏在窄布局下优先级比新建 project 高的问题；
- [x] 前端渲染问题右侧边栏宽度问题
- [x] 后端流式传输卡死问题
- [ ] MinerU API
- [ ] 前端强制占据浏览器问题
- [x] 前端复制问题
- [x] 前端 api key 不显示而是覆盖
- [x] 前端 chatview empty 页面 header 没有 sidebar 按钮的问题
- [x] 优化 skills
- [x] 删除 subagent
- [ ] 优化 docker 部署
- [ ] 优化文档
- [ ] 优化 agents 文档
- [ ] 优化 CI/CD