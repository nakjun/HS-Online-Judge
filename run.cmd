@echo off
setlocal
title Python Judge - Startup
cd /d "%~dp0"
echo Python Judge - starting...
echo Startup details will be saved to runtime\startup.log
echo.
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Python environment missing. Run install.cmd first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u "%~dp0launch.py" %*
set "launch_result=%errorlevel%"
if not "%launch_result%"=="0" (
  echo.
  echo Startup failed. Read the message above.
  pause
)
exit /b %launch_result%
