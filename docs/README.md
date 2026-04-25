# Backend Docs Index

这份索引用来说明后端文档应该从哪里开始看，以及每篇文档的用途。

## 建议阅读顺序

1. [../README.md](../README.md)
   - 后端总体能力、开发入口、测试入口、配置与部署入口
2. [workflow_quickstart.md](./workflow_quickstart.md)
   - 用最短路径验证 Data Process 主链路是否可用
3. [architecture.md](./architecture.md)
   - 当前实现的系统结构、运行流程、数据流和核心边界
4. [librarian.md](./librarian.md)
   - 检索与字段路径系统说明
5. [logging_conventions.md](./logging_conventions.md)
   - 日志字段和约定
6. [roadmap.md](./roadmap.md)
   - 后续规划

## 文档分工

### `workflow_quickstart.md`

面向“我要马上验证服务是否活着”的场景，强调：

- 如何启动服务
- 如何上传 PDF
- 如何查询任务状态
- 如何看处理结果

### `architecture.md`

面向“我要理解项目怎么工作的”场景，强调：

- 分层结构
- 关键模块职责
- 数据与状态流
- 配置与运行模式

### `librarian.md`

面向“我要查字段、做检索和对比”的场景，强调：

- projection / matrix / search 三类能力
- `field_path` 规则
- 典型查询模式

### `logging_conventions.md`

面向“我要排查问题和看运行日志”的场景，强调：

- 日志字段规范
- 推荐日志格式
- 常见事件命名

### `roadmap.md`

面向“我要知道哪些已经做完、哪些还没做”的场景，强调：

- 已完成事项
- 待做事项
- 未来可能的扩展方向

## 维护原则

为了避免文档继续漂移，后端文档后续按下面的规则维护：

- README 负责“入口”和“当前正确用法”
- `docs/` 负责解释机制和细节
- 已废弃接口、旧路由、旧命令不要继续保留在文档正文里
- 如果实现改动会影响用户操作路径，优先同时更新：
  - `README.md`
  - `docs/workflow_quickstart.md`
  - `tests/README.md`（如影响测试方式）
