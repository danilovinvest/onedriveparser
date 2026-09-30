@echo off
setlocal
title Mise a jour OneDrive MCP pour Claude Desktop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Update %*
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (
    echo Mise a jour terminee.
) else (
    echo La mise a jour a echoue, code %CODE%. Lis le message en rouge ci-dessus.
)
pause
exit /b %CODE%
