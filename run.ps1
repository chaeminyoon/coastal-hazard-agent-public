$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
    throw "가상환경이 없습니다. README.md의 최초 설치 절차를 실행하세요."
}

if (-not (Test-Path -LiteralPath ".\frontend\dist\index.html")) {
    Push-Location -LiteralPath ".\frontend"
    try {
        npm install
        npm run build
    }
    finally {
        Pop-Location
    }
}

Write-Host "연안 인텔리전스 스튜디오: http://127.0.0.1:8000" -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m uvicorn coastal_web.main:app `
    --app-dir ".\backend" --host "127.0.0.1" --port 8000
