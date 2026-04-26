# Librarian 系统详细设计方案

Librarian 不是一个单一的搜索框，而是一个提供**“精准寻址、多维检索、矩阵拼装”**的服务层。设计分为四层结构。

## Layer 1: 基础寻址与精细投影层 (Data Projection Layer)

这一层解决最基础的问题：**“我已经知道了 `paper_id`，我如何极其精准地只拿我想要的那一丁点数据，绝不带冗余上下文？”**

### 设计方案：基于 JSON Path 的点索引（Dot-Notation）寻址
利用 SQLite 原生极度强大的 `json_extract` 函数，实现任意层级、任意节点的精准提取。

**核心基础函数：`fetch_by_path(paper_id: str, field_path: str)`**

*   `field_path` 的语法规范：
    *   `meta` (获取整棵元数据树：title, authors, year等)
    *   `quick_scan.verdict` (直接获取字符串："推荐精读")
    *   `synthesis_data.methodology.innovation` (获取完整的 `CitedText` 对象)
    *   `analysis_report.derivation_steps` (获取列表)
**Python/SQL 伪代码实现思路：**
```python
def fetch_by_path(paper_id: str, field_path: str):
    # 路由映射表：判断根节点属于哪个 SQLite Column
    root_col_map = {
        "meta": "meta_json",
        "quick_scan": "quick_scan",
        "synthesis_data": "synthesis_data",
        "analysis_report": "theory_data"
    }
    root, *rest = field_path.split(".")
    column = root_col_map[root]
    
    # 构建 SQLite JSON Path (如：'$.methodology.innovation')
    json_path = "$." + ".".join(rest) if rest else "$"
    
    query = f"SELECT json_extract({column}, ?) FROM papers WHERE id = ?"
    cursor.execute(query, (json_path, paper_id))
    result = cursor.fetchone()[0]
    
    value = json.loads(result) # 返回精准切片数据
    return value
```

---

## Layer 2: 统一搜索引擎层 (Unified Search Engine)

这一层解决：**“我不知道 `paper_id`，我如何用统一表达式找到满足条件的论文集合？”**

Layer 2 使用单一引擎：**Unified Filter Engine**。

### 输入契约

Unified Filter Engine 输入包含：

1. `project_id`（可选）：
   *   指定时仅在项目内搜索。
   *   不指定时在全库搜索。
2. 组合条件表达式（新 DSL）：
   *   支持嵌套 `and/or` 条件组。
   *   条件字段通过 projection 语法指定，可定位 JSON 的任意层级路径。
   *   支持的根对象：
       *   `meta`（如 `meta.title`, `meta.year`）
       *   `md_content`
       *   `quick_scan`（如 `quick_scan.verdict`）
       *   `synthesis_data`（如 `synthesis_data.methodology.innovation.text`）
       *   `analysis_report`（如 `analysis_report.core_formulation.objective_function.text`）
3. 分页参数（可选）：`limit` / `offset`。

### 条件语义

*   `year`：仅支持范围语义（`BETWEEN`）。
*   其他字段：仅支持 `CONTAINS` 字符串包含匹配。
*   `CONTAINS` 匹配规则：
    *   大小写不敏感。
    *   对 JSON 字段按文本化后匹配（可命中 JSON 子结构中的目标字符串）。

### 输出契约

*   搜索返回结果为 `list[paper_id]`（可附带 `total/limit/offset` 分页元信息）。
*   Layer 2 不返回大体量正文切片，避免上下文膨胀。

### 自动质量过滤（强制）

Unified Filter Engine 在任意查询下都会自动追加以下过滤条件：

*   `extraction_status` 必须为 `COMPLETED` 或 `HUMAN_COMPLETED`
*   `extraction_fact_check_status` 必须为 `PASSED` 或 `HUMAN_PASSED`
*   `analysis_fact_check_status` 必须为 `PASSED` 或 `HUMAN_PASSED`

不满足上述条件的论文不会进入结果集。

---

## Layer 3: 高级组合检索能力 (Agent Toolbox Layer)

这一层是将 Layer 1 和 Layer 2 进行有机组合，包装成符合 LiteLLM Tool-Calling 规范的、面向 Agent（或前端页面）的超级工具。

当前实现中，`global_finder`、`matrix_compare` 与 `search_paper` 都可作为 Agent Tool 使用。

### Tool: 全局发现者 (Global Finder)
**能力**：聚合指定 project 下全部已关联论文的最基础信息，帮助 Agent 先建立对整批文献的整体感觉。

*   **返回内容**：
    *   每篇论文的 `paper_id / title / authors / year / quick_scan`
    *   全体统计信息：
        *   `paper_count`
        *   `year_distribution`
        *   `top_tags`
*   **年份统计字段**：
    *   `mean`
    *   `variance`
    *   `median`
    *   `mode_years`
    *   `q25`
    *   `q75`
    *   `outlier_count`
    *   `low_outlier_count`
    *   `high_outlier_count`
*   **离群值口径**：
    *   小于 5% 分位数的年份计入 `low_outlier_count`
    *   大于 95% 分位数的年份计入 `high_outlier_count`
*   **热门标签口径**：
    *   统计 `quick_scan.tags` 出现次数
    *   默认返回前 8 个标签（可通过配置 `librarian.top_tags_limit` 调整）

### Tool: 矩阵分析仪 (Matrix Compare) - **最核心能力！**
**能力**：利用 Layer 1 的点索引能力，在多篇论文间进行“横向拉网式”的数据穿透。
实现上，矩阵由 librarian 层循环调用 `fetch_by_path` 组装（而非 repository 内置 `matrix_fetch`）。
*   **Input Schema**:
    ```json
    {
      "paper_ids": ["doc_1", "doc_2", "doc_3"],
      "field_paths": [
        "synthesis_data.methodology.innovation",
        "analysis_report.core_formulation.objective_function"
      ]
    }
    ```
*   **Output (二维矩阵)**:
    ```json
    {
      "doc_1": {
        "synthesis_data.methodology.innovation": {"text": "...", "citations": [...]},
        "analysis_report.core_formulation.objective_function": {"text": "...", "citations": [...]}
      },
      "doc_2": { ... }
    }
    ```
*   **价值**：Writer Agent 撰写综述“对比分析”章节时，无需通读原文，瞬间拿到带引用的二维对比表格，直接开始撰写。

`projection` 仍主要通过 API 路由提供；`search_paper` 则同时支持 API 与 Agent Tool。

### 规划中能力说明（未实现）

- 深潜器（Deep Diver）当前仍处于规划阶段，属于“尚未实现”。
- 当前已落地能力包括 `global_finder`、`projection`、`search`、`matrix`，其中 `global_finder` / `search_paper` / `matrix_compare` 也可供 Agent 调用。

---

## Layer 4: FastAPI 架构落地规范

为了让 Claude Code 快速实现，以下是目录结构和代码组织建议：

1.  **数据库访问层 (`src/database/repository.py`)**
    负责实现 Layer 1 和 Layer 2 的所有 SQL/Chroma 裸操作，不涉及业务逻辑。
    包含 `get_json_path()`, `fts_search()`, `chroma_search()` 等。

2.  **核心服务层 (`src/tools/librarian.py`)**
    实现 Layer 3 的业务逻辑。
    ```python
    class LibrarianService:
        def __init__(self, db_repo):
            self.repo = db_repo
            
        def global_finder(self, request: GlobalFinderReq) -> list[dict]: ...
        def matrix_compare(self, request: MatrixCompareReq) -> dict: ...
        def deep_diver(self, request: DeepDiverReq) -> str: ...
    ```

3.  **Agent 工具绑定 (`src/agents/tools_config.py`)**
    将 `LibrarianService` 中的方法映射为 LLM 可以调用的 JSON Schema。
    ```python
    LIBRARIAN_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "matrix_compare",
                "description": "当需要对比多篇论文的特定细节时调用此工具。必须传入合法的 paper_ids 和点索引 field_paths。",
                "parameters": MatrixCompareReq.model_json_schema() # Pydantic 魔法直接生成 Schema
            }
        },
        # ... 其他工具
    ]
    ```

4.  **前端人类 API (`src/api/routers/librarian.py`)**
    除了供 Agent 使用，这套 Service 完全可以通过 FastAPI 的 `@router.post("/api/librarian/matrix")` 直接暴露给 Vue 前端。
    人类在前端工作台（Workspace）中，勾选几篇论文，选择想要对比的字段，就能立刻生成一个强大的**可视化知识比对表格**。

---

## 已实现接口（当前代码）

- `POST /api/v1/librarian/projection`
- `POST /api/v1/librarian/matrix`
- `POST /api/v1/librarian/search`
- `POST /api/v1/librarian/global-finder`
- `GET /api/v1/librarian/guide`

### Global Finder 请求示例

```json
{
    "project_id": "proj_1"
}
```

### Global Finder 响应示例

```json
{
    "project_id": "proj_1",
    "papers": [
        {
            "paper_id": "paper_123",
            "title": "A Great Paper",
            "authors": ["Alice", "Bob"],
            "year": 2024,
            "quick_scan": {
                "tags": ["优化算法", "控制策略"],
                "verdict": "推荐精读",
                "reason": "方法和实验都比较扎实",
                "quick_summary": "..."
            }
        }
    ],
    "stats": {
        "paper_count": 12,
        "top_tags_limit": 8,
        "year_distribution": {
            "available_count": 10,
            "missing_count": 2,
            "mean": 2022.4,
            "variance": 1.84,
            "median": 2022.0,
            "mode_years": [2022],
            "q25": 2021.25,
            "q75": 2024.0,
            "outlier_count": 1,
            "low_outlier_count": 0,
            "high_outlier_count": 1
        },
        "top_tags": [
            {"tag": "优化算法", "count": 6},
            {"tag": "控制策略", "count": 4}
        ]
    }
}
```

### Unified Search 请求示例

`search` 现在支持两种输入模式：

1. `paper_id` 精确搜索
2. `query_expr` 条件表达式搜索

### Unified Search 请求示例（query_expr）

```json
{
    "project_id": "proj_1",
    "query_expr": "(meta.year BETWEEN [2020, 2025]) AND (quick_scan.verdict CONTAINS 推荐)",
    "limit": 20,
    "offset": 0
}
```

### Unified Search 请求示例（paper_id）

```json
{
    "project_id": "proj_1",
    "paper_id": "paper_123",
    "limit": 20,
    "offset": 0
}
```

### Layer1 返回语义

- API 的 `projection` / `matrix` 返回原始结构，包含 `citations`。
- Agent Tool `matrix_compare_by_paths` 会在工具层剥离 `citations`，减少上下文膨胀。

### 错误码约定（细分）

- `404 not_found`：实体不存在
- `422 invalid_field`：字段不在白名单
- `422 invalid_operator`：操作符非法
- `422 invalid_value`：值类型或约束不合法
- `422 invalid_query_expr`：条件表达式语法不合法
