#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
BACKEND_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

export PPX_CONFIG_FILE="${PPX_CONFIG_FILE:-${BACKEND_ROOT}/config/dev.toml}"

cd "${BACKEND_ROOT}"
uv run fastapi dev src/paper_plane_x_backend/main.py
