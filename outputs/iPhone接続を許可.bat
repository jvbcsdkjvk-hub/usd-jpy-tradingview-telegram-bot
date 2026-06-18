@echo off
net session >nul 2>nul
if not %errorlevel%==0 (
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "if (-not (Get-NetFirewallRule -DisplayName 'USDJPY Signal Bot' -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName 'USDJPY Signal Bot' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private | Out-Null }"
echo iPhone access is allowed on private Wi-Fi networks.
pause
