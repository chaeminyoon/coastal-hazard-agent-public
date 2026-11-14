param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [string]$EnvFile = ".env.service",
    [switch]$ConfirmRestore
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) {
    throw "복구는 현재 DB와 산출물을 교체합니다. -ConfirmRestore 옵션을 지정하세요."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "deploy\compose.service.yml"
$ResolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
$DatabaseDump = Join-Path $ResolvedBackup "database.dump"
$ArtifactArchive = Join-Path $ResolvedBackup "artifacts.tar.gz"
if (-not (Test-Path -LiteralPath $DatabaseDump -PathType Leaf)) {
    throw "database.dump 파일이 없습니다."
}
if (-not (Test-Path -LiteralPath $ArtifactArchive -PathType Leaf)) {
    throw "artifacts.tar.gz 파일이 없습니다."
}

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

& docker @compose stop gateway api-1 api-2 worker
try {
    & docker cp $DatabaseDump "${postgresContainer}:/tmp/coastal-restore.dump"
    if ($LASTEXITCODE -ne 0) { throw "DB 백업 파일 전송에 실패했습니다." }
    & docker exec $postgresContainer sh -c `
        'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner /tmp/coastal-restore.dump'
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL 복구에 실패했습니다." }

    $dockerBackupPath = $ResolvedBackup.Replace("\", "/")
    & docker run --rm -v "${artifactVolume}:/target" alpine:3.21 `
        sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
    if ($LASTEXITCODE -ne 0) { throw "기존 산출물 정리에 실패했습니다." }
    & docker run --rm `
        -v "${artifactVolume}:/target" `
        -v "${dockerBackupPath}:/backup:ro" `
        alpine:3.21 tar -xzf /backup/artifacts.tar.gz -C /target
    if ($LASTEXITCODE -ne 0) { throw "보고서 산출물 복구에 실패했습니다." }
}
finally {
    & docker exec $postgresContainer rm -f /tmp/coastal-restore.dump | Out-Null
    & docker @compose up -d
}

Write-Host "복구 완료: $ResolvedBackup" -ForegroundColor Green
