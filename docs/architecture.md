# Backend Architecture

这份文档描述的是 **当前实现** 的后端结构，而不是早期的设想版架构。

## 1. 总体目标

后端的职责不是“做一个通用 Agent 平台”，而是把本项目的数据处理主链路做扎实：

- 单篇论文上传
- PDF 解析
- 双分支结构化提炼
- 双分支事实核查
- 数据持久化
- 为前端控制台与 Zotero 插件提供稳定 API

## 2. 分层结构

当前后端可以按下面的层次理解：

### 2.1 App 层

入口文件：

- `src/paper_plane_x_backend/main.py`

负责：

- 创建 FastAPI app
- 注册 routers
- 配置 CORS
- 处理 console fallback
- 在 lifespan 中初始化数据库和 worker pool

### 2.2 API 层

主要目录：

- `src/paper_plane_x_backend/api/routers/`
- `src/paper_plane_x_backend/api/dependencies.py`

负责：

- HTTP 入参校验与响应模型封装
- 领域错误到 HTTP 错误的映射
- WebSocket 连接管理（conversation、hitl）

当前路由分组：

| 路由              | 前缀         | 说明                       |
| ----------------- | ------------ | -------------------------- |
| `paper`           | `/api/v1`    | 论文 CRUD、上传、重处理    |
| `project`         | `/api/v1`    | 项目 CRUD、项目论文关联    |
| `librarian`       | `/api/v1`    | 检索、矩阵、投影、搜索     |
| `data_process`    | `/api/v1`    | 任务队列、取消、重试       |
| `conversation`    | `/api/v1`    | 对话 CRUD、消息 CRUD       |
| `conversation_ws` | `/api/v1/ws` | 流式对话 WebSocket         |
| `hitl`            | `/api/v1`    | HITL REST 占位（未来扩展） |
| `hitl_ws`         | `/api/v1/ws` | HITL 交互 WebSocket        |
| `agent_traces`    | `/api/v1`    | Agent trace 查询           |
| `settings`        | `/api/v1`    | LLM 配置、动态配置         |

API 层不直接写复杂业务逻辑，真正的流程控制放在 orchestrator / service / agent。

### 2.3 Orchestrator 层

主要目录：

- `src/paper_plane_x_backend/services/orchestrators/`

负责：

- Project、Paper、Data Process 等业务编排
- 跨 repository / task manager / parser / processor 的流程组合
- 对外暴露更清晰的业务边界

### 2.4 Service / Repository 层

主要目录：

- `src/paper_plane_x_backend/services/database.py`
- `src/paper_plane_x_backend/services/paper/`
- `src/paper_plane_x_backend/services/data_process_tasks/`

负责：

- SQLite 初始化与 schema 迁移
- Paper 数据访问
- Data Process 任务队列与 worker 生命周期
- 论文解析与处理流水线

### 2.5 Agent Runtime 层

主要目录：

- `src/paper_plane_x_backend/core/agent_runtime/`
- `src/paper_plane_x_backend/agents/`

负责：

- LLM 请求封装
- tool-call 循环
- structured output 校验
- trace 落库

## 3. 新增能力链路

### 3.1 Conversation 对话系统

项目级流式对话能力，通过 WebSocket 提供：

- **WebSocket 端点**：`/api/v1/ws/conversations/{conversation_id}`
- **REST 端点**：`/api/v1/conversations/*`
- **核心组件**：`ResearcherAgent`（基于 `BaseAgent` normal 模式）

ResearcherAgent 工具集：
- 文件沙箱：`read_project_file`、`write_project_file`、`list_project_files`、`remove_project_file`
- 文献检索：`global_finder`、`search_paper`、`matrix_compare`、`deep_dive`
- 论文笔记：`get_paper_agent_note`、`write_paper_agent_note`、`update_paper_agent_note`、`delete_paper_agent_note`
- 子任务委派：`delegate_to_subagent`
- 人机交互：`ask_human`

### 3.2 HITL (Human-in-the-loop)

Agent 可在关键决策点向人类提问并等待回答：

- **WebSocket 端点**：`/api/v1/ws/hitl`
- **工具**：`ask_human`（ResearcherAgent 可调用）
- **状态管理**：`HITLManager` 全局单例，管理 `PendingQuestion` 与 WebSocket 广播

流程：
1. Agent 调用 `ask_human`，传入问题列表（单选/多选 + 自定义回答选项）
2. `HITLManager` 注册问题并广播到所有 HITL WebSocket 客户端
3. 用户通过 WebSocket 提交回答
4. `ask_human` 被唤醒，返回回答结果给 Agent
5. 10 分钟超时保护

### 3.3 SubAgent 委派

ResearcherAgent 可通过 `delegate_to_subagent` 将复杂子任务委派给 SubAgent：

- SubAgent 不能调用 `delegate_to_subagent`（防止递归）
- SubAgent 拥有与 ResearcherAgent 相同的工具集（不含 subagent 工具）
- 适用于：综述段落撰写、多篇论文分析、独立研究任务

## 4. Data Process 主链路

当前最重要的一条链路是：

1. 上传 PDF
2. 创建或复用 paper 记录
3. 入队 data-process task
4. worker 消费任务
5. 解析 PDF -> 生成 Markdown / 图片
6. 并行执行两个分支：
   - Extraction
   - Analysis
7. 两个分支各自执行 Fact Check
8. 将结果写回 `papers`

### 3.1 上传阶段

入口接口：

- `POST /api/v1/papers`

主要逻辑：

- 计算上传文件 SHA256
- 根据 hash 判断是否复用已处理论文
- 创建 paper 记录
- 建立 task 并入队

### 3.2 处理阶段

worker 在后台执行：

- `PaperParser`：准备 `md_content` 与 `images`
- `DataProcessorAgentGroup`：并行跑双分支
- `PaperProcessor`：保存结果、更新状态、记录失败信息

### 3.3 状态模型

论文处理的关键状态分为三部分：

- `extraction_status`
- `extraction_fact_check_status`
- `analysis_fact_check_status`

常见组合：

- 完全通过：`COMPLETED + PASSED + PASSED`
- 部分失败待人工处理：`HUMAN_COMPLETED + ...FAILED...`
- 处理失败：`FAILED`

## 4. 数据模型与存储

当前主存储是 SQLite。

### 4.1 关键表

- `projects`
- `papers`
- `paper_projects`
- `agent_traces`
- `data_process_tasks`
- `papers_fts`
- `conversations`
- `conversation_messages`

### 4.2 `papers` 表存什么

`papers` 是整条链路的核心实体，保存：

- 论文基础元数据
- 原始 PDF 路径和 hash
- Markdown 与图片路径
- `quick_scan`
- `synthesis_data`
- `analysis_report`
- 两条分支的 fact check 状态与结果
- 重试计数

### 4.3 为什么用 JSON blob

对于 `quick_scan`、`synthesis_data`、`analysis_report` 等结构化产物，目前采用 JSON 文本直接存表，而不是进一步拆成多张业务表。

这么做的原因是：

- 当前字段演化频率较高
- 修改 schema 时更灵活
- 配合 `json_extract` 和 FTS5 已足够支撑当前搜索、导出和 UI 展示

## 5. 配置与环境

配置系统的核心是 `Settings`：

- `.env`
- `PPX_CONFIG_FILE`
- TOML profiles
- 环境变量覆盖

### 5.1 当前配置分工

- `config/default.toml`：默认基线
- `config/dev.toml`：本地开发
- `config/test.toml`：测试环境

### 5.2 后端特别关心的配置

- `database_path`
- `prompts_dir`
- `api.host`
- `api.port`
- `api.reload`
- `api.cors_allow_origins`
- `mineru.base_url`
- `data_process.worker_count`
- `llm.*`

## 6. Console 静态资源策略

后端不是前端开发服务器，但负责在部署或本地集成时托管 console 构建产物。

查找顺序：

1. `settings.api.console_dist_dir`
2. 仓库内 `paper_plane_x_frontend/dist`

如果没有构建产物，则根路径不会提供 console。

## 7. 部署边界

当前 Docker 化范围只覆盖后端本身。

意味着：

- SQLite、日志、PDF 解析产物通过 volume 持久化
- MinerU 默认视作外部服务，通过 `PPX_MINERU__BASE_URL` 指向
- 前端 console 可以单独构建后挂载，或者由后端 fallback 到已构建的 `dist`

## 8. 维护原则

为了降低后续漂移，这份架构文档遵循下面的约束：

- 只描述当前存在的模块和流程
- 不把“未来可能要做的设计”写进主叙述
- 如果 API、配置或处理链有明显变化，应同步更新：
  - `README.md`
  - `docs/workflow_quickstart.md`
  - 本文档
