#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE=".env.service"
DESTINATION="./backups"

while (($#)); do
  case "$1" in
    --env-file)
      ENV_FILE="${2:?--env-file requires a path}"
      shift 2
      ;;
    --destination)
      DESTINATION="${2:?--destination requires a path}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

resolve_from_root() {
  if [[ "$1" = /* ]]; then
    printf '%s\n' "$1"
  else
    printf '%s\n' "${PROJECT_ROOT}/${1#./}"
  fi
}

ENV_PATH="$(resolve_from_root "$ENV_FILE")"
DESTINATION_PATH="$(resolve_from_root "$DESTINATION")"
COMPOSE_FILE="${PROJECT_ROOT}/deploy/compose.service.yml"

if [[ ! -f "$ENV_PATH" ]]; then
  echo "Environment file not found: $ENV_PATH" >&2
  exit 1
fi

TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_PATH="${DESTINATION_PATH}/${TIMESTAMP}"
mkdir -p "$BACKUP_PATH"

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

cleanup() {
  docker exec "$POSTGRES_CONTAINER" rm -f /tmp/coastal.dump >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker exec "$POSTGRES_CONTAINER" sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/coastal.dump'
docker cp "${POSTGRES_CONTAINER}:/tmp/coastal.dump" "${BACKUP_PATH}/database.dump"
docker run --rm \
  -v "${ARTIFACT_VOLUME}:/source:ro" \
  -v "${BACKUP_PATH}:/backup" \
  alpine:3.21 tar -czf /backup/artifacts.tar.gz -C /source .

cat >"${BACKUP_PATH}/manifest.json" <<EOF
{
  "created_at": "$(date --iso-8601=seconds)",
  "database": "database.dump",
  "artifacts": "artifacts.tar.gz",
  "artifact_volume": "${ARTIFACT_VOLUME}"
}
EOF

echo "Backup completed: ${BACKUP_PATH}"
