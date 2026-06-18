@echo off
setlocal
cd /d "%~dp0"
title USDJPY Signal Bot Launcher

if exist ".venv\Scripts\python.exe" goto :launch

where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if defined PY goto :setup
where python >nul 2>nul
if errorlevel 1 goto :nopython
set "PY=python"

:setup
echo Preparing the bot for first use...
%PY% -m venv .venv
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :failed

:launch
echo Starting USDJPY Signal Bot...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\launch_bot.ps1"
if errorlevel 1 goto :failed
exit /b 0

:nopython
echo Python 3.11 or later was not found.
echo Install it from https://www.python.org/downloads/
pause
exit /b 1

:failed
echo Setup failed. Check the internet connection and Python installation.
pause
exit /b 1
