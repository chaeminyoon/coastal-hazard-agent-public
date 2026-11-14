param(
    [string]$EnvFile = ".env.service",
    [string]$Destination = ".\backups"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "deploy\compose.service.yml"
$DestinationPath = Join-Path $ProjectRoot $Destination
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupPath = Join-Path $DestinationPath $Timestamp
New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null

$compose = @("compose")
if ($EnvFile) {
    $EnvPath = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot $EnvFile)).Path
    $compose += @("--env-file", $EnvPath)
}
$compose += @("-f", $ComposeFile)
$postgresContainer = (& docker @compose ps -q postgres).Trim()
if (-not $postgresContainer) {
    throw "실행 중인 PostgreSQL 컨테이너를 찾을 수 없습니다."
}
$artifactVolume = (& docker volume ls `
    --filter "label=com.docker.compose.project=coastal-agent-service" `
    --filter "label=com.docker.compose.volume=report-artifacts" `
    --format "{{.Name}}").Trim()
if (-not $artifactVolume) {
    throw "보고서 산출물 볼륨을 찾을 수 없습니다."
}

& docker exec $postgresContainer sh -c `
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/coastal.dump'
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL 백업에 실패했습니다." }
try {
    & docker cp "${postgresContainer}:/tmp/coastal.dump" `
        (Join-Path $BackupPath "database.dump")
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL 백업 파일 복사에 실패했습니다." }
}
finally {
    & docker exec $postgresContainer rm -f /tmp/coastal.dump | Out-Null
}

$dockerBackupPath = $BackupPath.Replace("\", "/")
& docker run --rm `
    -v "${artifactVolume}:/source:ro" `
    -v "${dockerBackupPath}:/backup" `
    alpine:3.21 tar -czf /backup/artifacts.tar.gz -C /source .
if ($LASTEXITCODE -ne 0) { throw "보고서 산출물 백업에 실패했습니다." }

@{
    created_at = (Get-Date).ToString("o")
    database = "database.dump"
    artifacts = "artifacts.tar.gz"
    artifact_volume = $artifactVolume
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $BackupPath "manifest.json") -Encoding UTF8

Write-Host "백업 완료: $BackupPath" -ForegroundColor Green
