@echo off
setlocal
title Python Judge - Startup
cd /d "%~dp0"
echo Python Judge - starting...
echo Startup details will be saved to runtime\startup.log
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
set "launch_result=%errorlevel%"
if not "%launch_result%"=="0" (
  echo.
  echo Startup failed. Read the message above.
  pause
)
exit /b %launch_result%
