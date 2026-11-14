#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_PATH="${PROJECT_ROOT}/.venv-mcp"
VENDOR_PATH="${PROJECT_ROOT}/vendor/Data-Analyze-MCP"
BASE_PYTHON="${PYTHON:-python3}"

if [[ ! -f "${VENDOR_PATH}/pyproject.toml" ]]; then
  echo "vendor/Data-Analyze-MCP가 없습니다. 먼저 저장소를 내려받으세요." >&2
  exit 1
fi

if [[ ! -x "${VENV_PATH}/bin/python" ]]; then
  "$BASE_PYTHON" -m venv "$VENV_PATH"
fi

"${VENV_PATH}/bin/python" -m pip install "mcp>=1.27,<2" -e "$VENDOR_PATH"
"${VENV_PATH}/bin/python" -c \
  "import mcp, data_analysis; print('MCP environment ready')"
