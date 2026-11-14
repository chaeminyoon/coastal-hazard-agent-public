#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE=".env.service"
BACKUP_PATH=""
CONFIRM_RESTORE=false

while (($#)); do
  case "$1" in
    --env-file)
      ENV_FILE="${2:?--env-file requires a path}"
      shift 2
      ;;
    --backup-path)
      BACKUP_PATH="${2:?--backup-path requires a path}"
      shift 2
      ;;
    --confirm-restore)
      CONFIRM_RESTORE=true
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "$CONFIRM_RESTORE" != true ]]; then
  echo "Restore replaces the current database and artifacts. Pass --confirm-restore." >&2
  exit 1
fi
if [[ -z "$BACKUP_PATH" ]]; then
  echo "--backup-path is required." >&2
  exit 2
fi

resolve_from_root() {
  if [[ "$1" = /* ]]; then
    printf '%s\n' "$1"
  else
    printf '%s\n' "${PROJECT_ROOT}/${1#./}"
  fi
}

ENV_PATH="$(resolve_from_root "$ENV_FILE")"
RESOLVED_BACKUP="$(resolve_from_root "$BACKUP_PATH")"
COMPOSE_FILE="${PROJECT_ROOT}/deploy/compose.service.yml"
DATABASE_DUMP="${RESOLVED_BACKUP}/database.dump"
ARTIFACT_ARCHIVE="${RESOLVED_BACKUP}/artifacts.tar.gz"

for path in "$ENV_PATH" "$DATABASE_DUMP" "$ARTIFACT_ARCHIVE"; do
  if [[ ! -f "$path" ]]; then
    echo "Required file not found: $path" >&2
    exit 1
  fi
done

compose=(docker compose --env-file "$ENV_PATH" -f "$COMPOSE_FILE")
POSTGRES_CONTAINER="$("${compose[@]}" ps -q postgres)"
if [[ -z "$POSTGRES_CONTAINER" ]]; then
  echo "Running PostgreSQL container was not found." >&2
  exit 1
fi

ARTIFACT_VOLUME="$(
  docker volume ls \
    --filter "label=com.docker.compose.project=coastal-agent-service" \
    --filter "label=com.docker.compose.volume=report-artifacts" \
    --format '{{.Name}}'
)"
if [[ -z "$ARTIFACT_VOLUME" ]]; then
  echo "Report artifact volume was not found." >&2
  exit 1
fi

restart_services() {
  docker exec "$POSTGRES_CONTAINER" rm -f /tmp/coastal-restore.dump >/dev/null 2>&1 || true
  "${compose[@]}" up -d
}
trap restart_services EXIT

"${compose[@]}" stop gateway api-1 api-2 worker
docker cp "$DATABASE_DUMP" "${POSTGRES_CONTAINER}:/tmp/coastal-restore.dump"
docker exec "$POSTGRES_CONTAINER" sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner /tmp/coastal-restore.dump'
docker run --rm \
  -v "${ARTIFACT_VOLUME}:/target" \
  alpine:3.21 sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
docker run --rm \
  -v "${ARTIFACT_VOLUME}:/target" \
  -v "${RESOLVED_BACKUP}:/backup:ro" \
  alpine:3.21 tar -xzf /backup/artifacts.tar.gz -C /target

trap - EXIT
restart_services
echo "Restore completed: ${RESOLVED_BACKUP}"
