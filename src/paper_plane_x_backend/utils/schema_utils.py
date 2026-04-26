from typing import Any, cast


def strip_citations_recursively(value: Any) -> Any:
    if isinstance(value, list):
        return [strip_citations_recursively(item) for item in cast(list[Any], value)]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, raw in cast(dict[str, Any], value).items():
            if key == "citations":
                continue
            cleaned[key] = strip_citations_recursively(raw)
        return cleaned
    return value
