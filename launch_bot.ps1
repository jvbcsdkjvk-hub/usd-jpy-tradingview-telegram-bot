$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "run_bot.py"
$stdout = Join-Path $root "bot.log"
$stderr = Join-Path $root "bot-error.log"
$url = "http://127.0.0.1:8765"

$alreadyRunning = $false
try {
    Invoke-WebRequest -UseBasicParsing -Uri "$url/api/status" -TimeoutSec 2 | Out-Null
    $alreadyRunning = $true
} catch {}

if (-not $alreadyRunning) {
    Start-Process -FilePath $python -ArgumentList @($script) -WorkingDirectory $root `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
}

$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$url/api/status" -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {}
}

if (-not $ready) {
    Write-Host "The bot did not start. See bot-error.log." -ForegroundColor Red
    if (Test-Path $stderr) { Get-Content $stderr -Tail 20 }
    exit 1
}

Start-Process $url
Write-Host "USDJPY Signal Bot is running: $url" -ForegroundColor Green
