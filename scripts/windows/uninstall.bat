@echo off
setlocal
title Desinstallation OneDrive MCP
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
set "CODE=%ERRORLEVEL%"
pause
exit /b %CODE%
