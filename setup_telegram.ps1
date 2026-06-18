$ErrorActionPreference = "Stop"
$repo = "jvbcsdkjvk-hub/usd-jpy-tradingview-telegram-bot"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$env:GH_CONFIG_DIR = Join-Path $env:APPDATA "GitHub CLI"

Write-Host "Telegram Bot Setup" -ForegroundColor Cyan
Write-Host "1. Open @BotFather in Telegram and run /newbot."
Write-Host "2. Open the new bot and press Start or send /start."
Write-Host "3. Paste the BotFather token below. It will not be displayed."

$secureToken = Read-Host "Bot token" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }

if ([string]::IsNullOrWhiteSpace($token)) { throw "Bot token is empty." }
$me = Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getMe" -TimeoutSec 20
if (-not $me.ok) { throw "Invalid Telegram bot token." }
Write-Host "Bot verified: @$($me.result.username)" -ForegroundColor Green

$chatId = $null
for ($i = 0; $i -lt 20 -and -not $chatId; $i++) {
    $updates = Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getUpdates" -TimeoutSec 20
    $messages = @($updates.result | ForEach-Object { if ($_.message) { $_.message } elseif ($_.channel_post) { $_.channel_post } })
    if ($messages.Count -gt 0) { $chatId = $messages[-1].chat.id }
    if (-not $chatId) {
        Write-Host "Send /start to @$($me.result.username) in Telegram, then press Enter here."
        Read-Host | Out-Null
    }
}
if (-not $chatId) { throw "Chat ID was not found. Send /start to the bot and run this setup again." }

$token | & $gh secret set TELEGRAM_BOT_TOKEN --repo $repo
if ($LASTEXITCODE -ne 0) { throw "Failed to save TELEGRAM_BOT_TOKEN." }
$chatId.ToString() | & $gh secret set TELEGRAM_CHAT_ID --repo $repo
if ($LASTEXITCODE -ne 0) { throw "Failed to save TELEGRAM_CHAT_ID." }

$testBody = @{ chat_id = $chatId; text = "USD/JPY Signal Bot: Telegram connection successful." }
$sent = Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/sendMessage" -Body $testBody -TimeoutSec 20
if (-not $sent.ok) { throw "Telegram test notification failed." }

& $gh workflow enable telegram-signal.yml --repo $repo
& $gh workflow run telegram-signal.yml --repo $repo
Write-Host "Setup complete. Check Telegram for the test message." -ForegroundColor Green

