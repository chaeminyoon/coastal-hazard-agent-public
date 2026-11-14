$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPath = Join-Path $projectRoot ".venv-mcp"
$vendorPath = Join-Path $projectRoot "vendor\Data-Analyze-MCP"

if (-not (Test-Path -LiteralPath (Join-Path $vendorPath "pyproject.toml"))) {
    throw "vendor\Data-Analyze-MCP가 없습니다. 먼저 저장소를 내려받으세요."
}

if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) {
    & (Join-Path $projectRoot ".venv\Scripts\python.exe") -m venv $venvPath
}

$python = Join-Path $venvPath "Scripts\python.exe"
& $python -m pip install "mcp>=1.27,<2" -e $vendorPath
if ($LASTEXITCODE -ne 0) { throw "MCP 패키지 설치에 실패했습니다." }
& $python -c "import mcp, data_analysis; print('MCP environment ready')"
if ($LASTEXITCODE -ne 0) { throw "MCP 패키지를 불러오지 못했습니다." }
