# Paper Plane X Backend 开发指南

## 作用域与工具链

- 本文件适用于 backend 独立仓库。若在 monorepo 中开发，同时遵循上级 `AGENTS.md`；冲突时以本文件的项目级规则为准。
- 本项目是 Python 3.12+ 独立 uv package。依赖、命令和工具配置以 `pyproject.toml`、`uv.lock` 与本目录 `justfile` 为准，不使用根目录或其他子项目的环境代替。
- 开始修改前阅读相关模块、现有测试及 `docs/`。架构、功能状态和接口细节以代码、OpenAPI schema、测试与项目文档为事实源，不写入本文件维护平行清单。
- 常用命令：`just setup`、`just test [ARGS]`、`just lint`、`just format-check`、`just typecheck`、`just build`、`just pre-commit`。

## Python 与类型规则

- 新代码使用 Python 3.12+ 语法：使用 `T | None`、内建泛型和 `type` 语句等现代写法，不新增 `Optional[T]`、`List[T]` 等旧式标注。
- 核心路径不使用 `Any`、无类型 dict 或动态属性探测。第三方无类型边界集中在适配层，用明确的 `Protocol`、Pydantic model、dataclass、`TypedDict`、`Literal` / `Enum` 和显式 `cast` 收窄。
- 不使用无说明的 `# type: ignore`。确有必要时使用最窄的错误码范围，并在相邻注释说明第三方限制和移除条件。
- 普通业务代码不使用 `getattr`、`hasattr`、monkey patch 或字符串拼接属性名规避类型设计。
- 异步路径保持 async 边界，不在 event loop 中执行阻塞网络或文件操作；资源由 context manager、lifespan 或明确的关闭流程管理。

## 分层与边界

- HTTP router 负责协议解析、依赖注入和响应映射；业务编排放在 service / orchestrator；持久化集中在 database / repository。不要在 router、Agent tool 或测试夹具中直接散落 SQL 和跨层业务规则。
- API、Agent tool 和配置入口使用结构化 schema，不把内部对象或未验证 dict 直接暴露到边界。
- 外部 Agent 通过稳定 HTTP/CLI 契约接入，不从 CLI、前端或插件反向依赖 backend 内部模块。
- 数据库和文件操作必须保持项目已有的事务、路径沙箱和错误语义。涉及迁移、删除、覆盖或批量更新时，先确认回滚与旧数据兼容策略，不用启动时的隐式修复掩盖问题。
- 密钥字段始终按 write-only 处理；日志、异常、schema、测试快照和响应中不得暴露明文密钥或敏感文献内容。
- 不恢复已删除的 API、运行时或兼容面，除非任务明确要求并同时补齐迁移、消费者和文档。

## 实现约束

- 优先显式控制流和窄异常类型，不捕获宽泛 `Exception` 后继续运行。仅在进程、网络、文件、第三方 SDK 等边界转换异常，并保留原始 cause。
- 不添加静默 fallback、重复校验或未经测量的缓存。性能敏感的检索、解析和批处理路径应避免逐项 I/O 与隐式 N+1；优化必须保留可读性并有测量或测试依据。
- Prompt、结构化模型、工具 schema 和运行时行为属于同一契约；修改任一项时检查调用者、trace、错误映射和回归测试。
- 核心数学、排序、检索评分或其他非直观算法必须写明输入假设、公式含义、数值边界和复杂度，并在 `docs/` 中提供可审查的推导与验证说明。

## 测试与交付

- 新 route 或 HTTP 行为添加 integration test；repository、service、Agent runtime 和 tool 行为添加针对性的 unit test；缺陷修复先补能复现问题的回归用例。
- 测试使用临时目录、临时数据库和确定性 fake，不依赖开发者真实 `data/`、`.env`、网络服务或 API key。
- 小改动至少运行相关 `just test ...`、`just lint` 和 `just typecheck`；格式敏感改动运行 `just format-check`；包结构或发布内容变化运行 `just build`。高风险或跨层改动运行 `just pre-commit`。
- API schema、配置、持久化格式或外部 tool 变化时，同步更新 backend 文档及直接消费方；需要 CLI 暴露的能力同时检查 sibling `paper_plane_x_cli` 的命令、Skills 和参考文档。
- 不手改 `dist/`、运行时 `data/`、缓存或生成产物。不得声称未运行的验证已通过；失败需报告命令、失败项和与本次改动的关系。
