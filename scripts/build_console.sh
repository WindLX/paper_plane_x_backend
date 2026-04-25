#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
BACKEND_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
FRONTEND_DIR="${BACKEND_ROOT}/../paper_plane_x_frontend"

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is required but not found in PATH." >&2
  exit 1
fi

pnpm --dir "${FRONTEND_DIR}" build:console
echo "Console build output: ${BACKEND_ROOT}/data/console"
