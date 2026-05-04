"""结构化输出校验与 JSON 候选提取工具."""

import json
import logging
import re
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from paper_plane_x_backend.core.agent_runtime.exceptions import AgentValidationError

logger = logging.getLogger(__name__)


def sanitize_json_string_escapes(raw: str) -> str:
    """修复 JSON 字符串内部非法转义（常见于未转义 LaTeX 反斜杠）。"""
    valid_escape_chars = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}
    result: list[str] = []
    in_string = False
    idx = 0
    length = len(raw)

    while idx < length:
        ch = raw[idx]

        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
            idx += 1
            continue

        if ch == '"':
            in_string = False
            result.append(ch)
            idx += 1
            continue

        if ch == "\\":
            if idx + 1 >= length:
                result.append("\\\\")
                idx += 1
                continue

            next_char = raw[idx + 1]
            if next_char in valid_escape_chars:
                result.append("\\")
                result.append(next_char)
                idx += 2
                continue

            result.append("\\\\")
            idx += 1
            continue

        result.append(ch)
        idx += 1

    return "".join(result)


def load_json_object_candidate(raw: str) -> dict[str, Any] | None:
    """尝试将原始文本片段解析为 JSON 对象."""
    try:
        loaded: Any = json.loads(raw)
    except json.JSONDecodeError:
        sanitized = sanitize_json_string_escapes(raw)
        if sanitized == raw:
            return None
        logger.debug(
            "event=agent.json_sanitize_applied stage=candidate candidate_length=%s sanitized_length=%s",
            len(raw),
            len(sanitized),
        )
        try:
            loaded = json.loads(sanitized)
        except json.JSONDecodeError:
            logger.debug(
                "event=agent.json_sanitize_failed stage=candidate candidate_length=%s",
                len(raw),
            )
            return None
    if isinstance(loaded, dict):
        return cast(dict[str, Any], loaded)
    return None


def extract_json_candidates_from_code_fences(content: str) -> list[str]:
    """提取 fenced code block 中可能的 JSON 片段."""
    fence_pattern = re.compile(r"```([^\n`]*)\n?([\s\S]*?)```")
    json_fences: list[str] = []
    other_fences: list[str] = []

    for match in fence_pattern.finditer(content):
        language = (match.group(1) or "").strip().lower()
        candidate = (match.group(2) or "").strip()
        if not candidate:
            continue
        if language == "json":
            json_fences.append(candidate)
        else:
            other_fences.append(candidate)

    return json_fences + other_fences


def extract_json_candidates_from_text(content: str) -> list[str]:
    """从普通文本中扫描花括号包裹的 JSON 候选."""
    candidates: list[str] = []
    length = len(content)

    for start in range(length):
        if content[start] != "{":
            continue

        depth = 0
        in_string = False
        escaped = False

        for end in range(start, length):
            ch = content[end]

            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = content[start : end + 1].strip()
                    if candidate:
                        candidates.append(candidate)
                    break
                if depth < 0:
                    break

    return candidates


def collect_json_object_candidates(content: str) -> list[tuple[int, dict[str, Any]]]:
    """收集并解析所有 JSON 对象候选，按长度倒序排列."""
    candidates: list[tuple[int, dict[str, Any]]] = []
    raw_candidates: list[str] = []
    raw_candidates.extend(extract_json_candidates_from_code_fences(content))
    raw_candidates.extend(extract_json_candidates_from_text(content))

    seen_raw: set[str] = set()
    for raw in raw_candidates:
        normalized = raw.strip()
        if not normalized or normalized in seen_raw:
            continue
        seen_raw.add(normalized)

        loaded = load_json_object_candidate(normalized)
        if loaded is not None:
            candidates.append((len(normalized), loaded))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates


def validate_output_content(
    content: str,
    *,
    output_schema: type[BaseModel],
    agent_name: str,
) -> BaseModel:
    """校验模型输出是否满足目标 schema。"""
    original_error: AgentValidationError | None = None

    try:
        direct_loaded = json.loads(content)
        if not isinstance(direct_loaded, dict):
            raise AgentValidationError(
                message="Invalid JSON output: root type must be JSON object",
                agent_name=agent_name,
                raw_output=content,
            )
        else:
            try:
                return output_schema.model_validate(direct_loaded)
            except ValidationError as exc:
                original_error = AgentValidationError(
                    message=f"Schema validation failed: {exc}",
                    agent_name=agent_name,
                    validation_errors=[dict(err) for err in exc.errors()],
                    raw_output=content,
                )
    except json.JSONDecodeError:
        pass

    if original_error is None:
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            original_error = AgentValidationError(
                message=f"Invalid JSON output: {exc}",
                agent_name=agent_name,
                raw_output=content,
            )

    sanitized = sanitize_json_string_escapes(content)
    if sanitized != content:
        logger.debug(
            "event=agent.json_sanitize_applied stage=direct content_length=%s sanitized_length=%s",
            len(content),
            len(sanitized),
        )
        try:
            direct_loaded = json.loads(sanitized)
            if not isinstance(direct_loaded, dict):
                raise AgentValidationError(
                    message="Invalid JSON output: root type must be JSON object",
                    agent_name=agent_name,
                    raw_output=content,
                )
            try:
                return output_schema.model_validate(direct_loaded)
            except ValidationError:
                pass
        except json.JSONDecodeError:
            logger.debug(
                "event=agent.json_sanitize_failed stage=direct content_length=%s",
                len(content),
            )

    json_candidates = collect_json_object_candidates(content)
    if not json_candidates:
        if original_error is not None:
            raise original_error

        raise AgentValidationError(
            message="Invalid JSON output: root type must be JSON object",
            agent_name=agent_name,
            raw_output=content,
        )

    last_validation_error: ValidationError | None = None
    try:
        for _, data in json_candidates:
            try:
                return output_schema.model_validate(data)
            except ValidationError as exc:
                last_validation_error = exc

        if last_validation_error is not None:
            if original_error is not None:
                raise original_error
            raise last_validation_error

        raise AgentValidationError(
            message="Schema validation failed: no valid JSON object candidate",
            agent_name=agent_name,
            raw_output=content,
        )
    except ValidationError as exc:
        if original_error is not None:
            raise original_error
        raise AgentValidationError(
            message=f"Schema validation failed: {exc}",
            agent_name=agent_name,
            validation_errors=[dict(err) for err in exc.errors()],
            raw_output=content,
        ) from exc
