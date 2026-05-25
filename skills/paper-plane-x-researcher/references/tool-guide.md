# Paper Plane X CLI Tool Guide

`ppx` is the HTTP bridge from external agents to Paper Plane X. It calls FastAPI endpoints and prints JSON.

## Context

```bash
ppx context set --base-url http://127.0.0.1:8000/api/v1 --project-id prj_x
ppx context show
```

Context precedence is:

1. Command flags: `--base-url`, `--project-id`
2. Environment variables: `PPX_BASE_URL`, `PPX_PROJECT_ID`
3. Saved context: `~/.config/paper-plane-x/context.json`
4. Default base URL: `http://127.0.0.1:8000/api/v1`

Run `ppx context show` before project-scoped work. Most project file and project librarian commands require `project_id`.

## Tool Name To CLI Mapping

### Project Files

| Researcher tool | CLI command |
| --- | --- |
| `list_project_files` | `ppx files list --dir /` |
| `read_project_file` | `ppx files read --path /notes/idea.md` |
| `read_project_file_lines` | `ppx files lines --path /draft.md --start-line 10 --end-line 20` |
| `find_in_project_file` | `ppx files find --path /draft.md --query "Related Work"` |
| `write_project_file` | `ppx files write --path /notes/summary.md --content "..."` |
| `replace_project_file_lines` | `ppx files replace-lines --path /draft.md --start-line 4 --end-line 6 --new-text "..."` |
| `replace_project_file_text` | `ppx files replace-text --path /draft.md --old-text "..." --new-text "..."` |
| `patch_project_file` | `ppx files patch --path /draft.md --action insert_after --anchor-text "## Methods\n" --content "..."` |
| `remove_project_file` | `ppx files delete --path /tmp/old.md` |

Patch actions are `replace`, `insert_before`, `insert_after`, and `delete`. `replace-text` and `patch` support `--expected-occurrences`; use it to avoid accidental multi-match edits. `replace-text` also supports `--replace-all`.

### Paper Notes

| Researcher tool | CLI command |
| --- | --- |
| `get_paper_agent_note` | `ppx paper-note get --paper-id p1` |
| `write_paper_agent_note` | `ppx paper-note write --paper-id p1 --content "..."` |
| `update_paper_agent_note` | `ppx paper-note write --paper-id p1 --content "..."` |
| `delete_paper_agent_note` | `ppx paper-note delete --paper-id p1` |

Paper notes are for stable, reusable conclusions about one paper.

### Librarian

| Researcher tool | CLI command |
| --- | --- |
| `global_finder` | `ppx project global-finder` |
| `search_paper` | `ppx librarian search --query-expr "(meta.title CONTAINS transformer)" --limit 20` |
| `matrix_compare` | `ppx librarian matrix --paper-ids p1,p2 --field-paths quick_scan,synthesis_data.methodology.innovation` |
| `deep_dive` | `ppx librarian deep-dive --paper-id p1 --question "What is the main control objective?"` |

Use `search_paper` to find candidate `paper_id`s, `matrix_compare` to compare structured fields, and `deep_dive` for focused single-paper questions that cannot be answered from structured fields.

## Query Examples

```bash
ppx librarian search --query-expr "(meta.title CONTAINS transformer)"
ppx librarian search --query-expr "(md_content CONTAINS lyapunov)"
ppx librarian search --query-expr "(meta.year BETWEEN [2020, 2025]) AND (quick_scan.verdict CONTAINS 推荐)"
ppx librarian search --query-expr "(meta.title CONTAINS \"deep learning\") OR (meta.publication CONTAINS NeurIPS)"
```

Rules:

- Use parentheses around conditions.
- Combine conditions with `AND` and `OR`.
- Use `CONTAINS` for text fields.
- Use `BETWEEN [start, end]` for `year` / `meta.year`.
- Quote values with spaces or special characters.

## Matrix Field Examples

```bash
ppx librarian matrix --paper-ids p1,p2 --field-paths meta,quick_scan
ppx librarian matrix --paper-ids p1,p2 --field-paths quick_scan.verdict,quick_scan.tags
ppx librarian matrix --paper-ids p1,p2 --field-paths synthesis_data.methodology.innovation,analysis_report.core_formulation.objective_function
```

Prefer specific field paths over broad roots when possible. This keeps context small and makes comparisons easier.

## File Editing Examples

Inspect before editing:

```bash
ppx files list --dir /
ppx files find --path /draft.md --query "Related Work"
ppx files lines --path /draft.md --start-line 20 --end-line 40
```

Small line edit:

```bash
ppx files replace-lines --path /draft.md --start-line 24 --end-line 29 --new-text "new paragraph"
```

Anchor edit:

```bash
ppx files patch --path /draft.md --action insert_after --anchor-text "## Related Work\n" --content "new content\n"
```

Whole-file write, only when intended:

```bash
ppx files write --path /notes/lit-review.md --content "# Literature Review\n..."
```

## Output Handling

- Every command prints JSON.
- Treat a JSON `error` or non-zero command exit as a failed tool call.
- Do not infer missing paper facts from filenames, titles, or prior memory; fetch evidence with librarian tools.
