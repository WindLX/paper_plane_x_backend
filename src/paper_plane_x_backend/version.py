"""Shared application version helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT_BACKEND = Path(__file__).resolve().parents[3]
VERSION_FILE = REPO_ROOT / "VERSION"
VERSION_FILE_BACKEND = REPO_ROOT_BACKEND / "VERSION"


@lru_cache(maxsize=1)
def get_app_version() -> str:
    try:
        value = VERSION_FILE.read_text(encoding="utf-8").strip()
        value_backend = VERSION_FILE_BACKEND.read_text(encoding="utf-8").strip()
        value_str = (
            value if value == value_backend else f"{value} (backend: {value_backend})"
        )
    except FileNotFoundError:
        return "unknown"
    return value_str
