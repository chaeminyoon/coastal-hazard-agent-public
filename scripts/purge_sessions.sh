#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-.env.service}"

if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="${PROJECT_ROOT}/${ENV_FILE#./}"
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found: $ENV_FILE" >&2
  exit 1
fi

docker compose \
  --env-file "$ENV_FILE" \
  -f "${PROJECT_ROOT}/deploy/compose.service.yml" \
  run --rm api-1 \
  python -m coastal_web.maintenance_cli purge-sessions
