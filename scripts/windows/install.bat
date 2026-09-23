@echo off
setlocal
title Installation OneDrive MCP pour Claude Desktop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (
    echo Tout est pret.
) else (
    echo L'installation a echoue, code %CODE%. Lis le message en rouge ci-dessus.
)
pause
exit /b %CODE%
