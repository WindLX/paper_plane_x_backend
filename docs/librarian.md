# Librarian, Project Files, Paper Notes, and External Researcher Tools

这份文档面向用户、前端开发者、后端开发者和外部 agent。它描述当前真实可用的检索、矩阵、deep dive、项目文件、论文笔记、`ppx` CLI 与 Researcher skill。

## 1. 能力概览

Librarian 不是一个普通搜索框，而是一组面向研究工作流的能力：

- `global-finder`：项目级文献总览和统计。
- `search`：使用 DSL 在项目或全库范围内搜索 paper ids。
- `matrix`：按 `paper_ids` 和 `field_paths` 拉取结构化字段，适合跨论文比较。
- `deep-dive`：对单篇论文提出具体问题，调用 DeepDiverAgent 返回结构化答案。
- `query-builder`：把自然语言查询转换为 Librarian DSL。

Researcher 还配套两类项目资产工具：

- Project files：项目沙箱里的 Markdown / text / JSON / CSV / YAML 文件。
- Paper notes：单篇论文的长期 AI 笔记 `agent_note`。

外部 agent 使用这些能力时，推荐走 `ppx` CLI 或 `../paper_plane_x_cli/skills/ppx-researcher`。

## 2. API

### 2.1 Librarian

- `POST /api/v1/librarian/global-finder`
- `POST /api/v1/librarian/global-finder/agent-summary`
- `POST /api/v1/librarian/search`
- `POST /api/v1/librarian/matrix`
- `POST /api/v1/librarian/deep-dive`
- `POST /api/v1/librarian/query-builder`
- `POST /api/v1/projects/{project_id}/search`

### 2.2 Project files

- `GET /api/v1/projects/{project_id}/files?dir_path=/`
- `GET /api/v1/projects/{project_id}/files/content?file_path=/notes/a.md`
- `GET /api/v1/projects/{project_id}/files/download?file_path=/notes/a.md`
- `PUT /api/v1/projects/{project_id}/files/content`
- `POST /api/v1/projects/{project_id}/files/upload`
- `DELETE /api/v1/projects/{project_id}/files/content?file_path=/notes/a.md`
- `GET /api/v1/projects/{project_id}/files/lines`
- `GET /api/v1/projects/{project_id}/files/find`
- `PATCH /api/v1/projects/{project_id}/files/lines`
- `PATCH /api/v1/projects/{project_id}/files/text`
- `PATCH /api/v1/projects/{project_id}/files/patch`
- `POST /api/v1/projects/{project_id}/files/export`

`/files/download` 以附件返回沙箱文件在磁盘上的原始字节，不做 UTF-8 解码；
路径、扩展名白名单和 10MB 上限与其它 project files 接口一致。中文等非 ASCII 文件名
通过 RFC 5987 的 `filename*=UTF-8''...` 形式放在 `Content-Disposition` 中。

### 2.3 Paper notes

- `GET /api/v1/papers/{paper_id}/agent-note`
- `PUT /api/v1/papers/{paper_id}/agent-note`
- `PATCH /api/v1/papers/{paper_id}/agent-note`
- `DELETE /api/v1/papers/{paper_id}/agent-note`

## 3. Query DSL

`query_expr` 使用括号、`AND`、`OR` 组织条件。

示例：

```text
(meta.title CONTAINS transformer)
(md_content CONTAINS lyapunov)
(meta.year BETWEEN [2020, 2025])
(meta.year BETWEEN [2020, 2025]) AND (quick_scan.verdict CONTAINS 推荐)
(meta.title CONTAINS "deep learning") OR (meta.publication CONTAINS NeurIPS)
```

规则：

- 文本字段使用 `CONTAINS`。
- 年份仅支持 `year` / `meta.year` 的 `BETWEEN [start, end]`。
- 文本包含空格或特殊字符时使用双引号。
- 搜索会自动过滤 extraction / fact check 状态不合格的论文。

## 4. Field Paths

常用根路径：

- `md_content`
- `meta`
- `quick_scan`
- `synthesis_data`
- `analysis_report`

常用字段：

- `meta.title`
- `meta.authors`
- `meta.year`
- `meta.publication`
- `meta.doi`
- `meta.custom_meta`
- `quick_scan.tags`
- `quick_scan.verdict`
- `quick_scan.reason`
- `quick_scan.quick_summary`
- `synthesis_data.research_gap.context.text`
- `synthesis_data.research_gap.existing_limit.text`
- `synthesis_data.research_gap.motivation.text`
- `synthesis_data.methodology.approach_name`
- `synthesis_data.methodology.core_logic.text`
- `synthesis_data.methodology.innovation.text`
- `synthesis_data.methodology.disadvantage.text`
- `synthesis_data.methodology.future_direction.text`
- `synthesis_data.key_results.dataset_env.text`
- `synthesis_data.key_results.baseline.text`
- `synthesis_data.key_results.performance.text`
- `synthesis_data.review_summary.text`
- `analysis_report.prerequisites[0].concept_name`
- `analysis_report.prerequisites[0].brief_explanation`
- `analysis_report.prerequisites[0].relevance_to_paper.text`
- `analysis_report.core_formulation.problem_definition.text`
- `analysis_report.core_formulation.objective_function.text`
- `analysis_report.core_formulation.algorithm_flow.text`
- `analysis_report.derivation_steps[0].step_name`
- `analysis_report.derivation_steps[0].detail_explanation.text`
- `analysis_report.related_references[0].title`
- `analysis_report.related_references[0].reason`

数组使用 `[index]` 访问，例如：

```text
analysis_report.prerequisites[0].concept_name
analysis_report.derivation_steps[0].detail_explanation.text
```

完整 field path guide 已内置在 [Researcher Skill](../../paper_plane_x_cli/skills/ppx-researcher/SKILL.md)。

## 5. API 示例

### 5.1 Global finder

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/librarian/global-finder \
  -H "Content-Type: application/json" \
  -d '{"project_id":"prj_x"}'
```

返回重点：

- `papers[]`: `paper_id`, `title`, `authors`, `year`, `quick_scan`
- `stats.paper_count`
- `stats.year_distribution`
- `stats.top_tags`
- `agent_summary`

### 5.2 Search

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/librarian/search \
  -H "Content-Type: application/json" \
  -d '{
    "project_id":"prj_x",
    "query_expr":"(quick_scan.tags CONTAINS 强化学习)",
    "limit":20,
    "offset":0
  }'
```

返回：

```json
{
  "project_id": "prj_x",
  "limit": 20,
  "offset": 0,
  "total": 12,
  "paper_ids": ["pap-a", "pap-b"]
}
```

### 5.3 Matrix

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/librarian/matrix \
  -H "Content-Type: application/json" \
  -d '{
    "paper_ids":["pap-a","pap-b"],
    "field_paths":[
      "meta.title",
      "quick_scan.quick_summary",
      "synthesis_data.methodology.innovation.text"
    ]
  }'
```

返回：

```json
{
  "paper_ids": ["pap-a", "pap-b"],
  "field_paths": ["meta.title"],
  "items": {
    "pap-a": {
      "meta.title": "..."
    }
  }
}
```

### 5.4 Deep dive

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/librarian/deep-dive \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id":"pap-a",
    "question":"这篇论文的核心创新是什么？请简短回答。"
  }'
```

## 6. `ppx` CLI

`ppx` 是外部 agent 推荐使用的入口。

```bash
uvx --from ../paper_plane_x_cli ppx --help
uv tool install ../paper_plane_x_cli
ppx context set --base-url http://127.0.0.1:8000/api/v1 --project-id prj_x
ppx context show
```

Librarian：

```bash
ppx project global-finder
ppx librarian search --query-expr "(meta.title CONTAINS transformer)" --limit 20
ppx librarian matrix --paper-ids pap-a,pap-b --field-paths meta.title,quick_scan.quick_summary
ppx librarian deep-dive --paper-id pap-a --question "核心创新是什么？"
```

Project files：

```bash
ppx files list --dir /
ppx files read --path /notes/survey.md
ppx files lines --path /notes/survey.md --start-line 1 --end-line 20
ppx files find --path /notes/survey.md --query "Related Work"
ppx files write --path /notes/idea.md --content "..."
ppx files upload --source ./idea.md --path /notes/idea.md
ppx files replace-lines --path /notes/idea.md --start-line 2 --end-line 3 --new-text "..."
ppx files replace-text --path /notes/idea.md --old-text "old" --new-text "new"
ppx files patch --path /notes/idea.md --action insert_after --anchor-text "## Section\n" --content "..."
ppx files delete --path /notes/tmp.md
```

Paper notes：

```bash
ppx paper-note get --paper-id pap-a
ppx paper-note write --paper-id pap-a --content "..."
ppx paper-note delete --paper-id pap-a
```

## 7. Project File Editing Guide

项目文件工具和外部 `ppx-researcher` skill 的编辑原则一致：

- 优先选择最小修改范围。
- 开始编辑前，先 list，再 read / lines。
- 定位文本时用 find。
- 已知行号时用 replace-lines。
- 旧文本稳定时用 replace-text。
- 围绕锚点插入、替换、删除时用 patch。
- 只有准备整体重写时才用 write。
- replace-text 和 patch 默认校验命中次数；命中数量不对时应先重新查找。
- 行号是 1-based，`end_line` 包含端点。
- 文件必须在项目沙箱内，扩展名仅允许 `.md`, `.txt`, `.json`, `.csv`, `.yaml`, `.yml`。
- 单文件大小上限为 10MB。

## 8. Researcher Skill

外部 agent 使用：

- [Researcher Skill](../../paper_plane_x_cli/skills/ppx-researcher/SKILL.md)
- [Tool Guide](../../paper_plane_x_cli/skills/ppx-researcher/references/tool-guide.md)

Skill 包含：

- Researcher 工作原则。
- Toolset shared guide。
- Librarian query rules。
- 完整 field paths。
- Project file / paper note / librarian 工具说明。
- `ppx` CLI 映射。

外部 agent 需要用户决策时直接问当前用户；复杂任务拆分由宿主 agent 自己处理。

## 9. 推荐研究流程

### 用户问一个研究问题

1. `global-finder` 建立项目整体感。
2. `search` 找候选论文。
3. `matrix` 拉取结构化证据。
4. 信息不够时对关键论文 `deep-dive`。
5. 回答中只引用实际查过的论文，格式为 `[[paper_id | short_title]]`。

### 用户要求写综述或草稿

1. `files list` 检查已有草稿。
2. `files read` / `lines` 读取上下文。
3. `search` / `matrix` 补证据。
4. 生成 Markdown。
5. 用 `files write`、`files upload` 或 patch 类命令保存。

### 用户要求比较多篇论文

1. 明确比较维度。
2. 用 `matrix` 拉取对应字段。
3. 个别关键细节用 `deep-dive`。
4. 输出先给结论，再给维度化对比。

## 10. 错误处理

常见错误：

- `404 not_found`：project / paper / task / file 不存在。
- `400 bad_request`：路径非法、文件类型不允许、文件过大、编辑锚点不匹配。
- `422 invalid_field`：query 或 field_path 不合法。
- `422 invalid_query_expr`：DSL 语法不合法。
- `500 agent_execution_error`：deep-dive 或 LLM 调用失败。

CLI 中所有错误都会以 JSON 打到 stderr，并返回非零退出码。
