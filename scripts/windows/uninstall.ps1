<#
.SYNOPSIS
    Désinstalle le serveur MCP OneDrive : retire l'entrée "onedrive" de Claude
    Desktop, supprime le token OneDrive et le dossier d'installation.
    uv et Python sont conservés (ils peuvent servir à autre chose).
#>
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "onedrive-mcp")
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

function Remove-ClaudeEntry([string]$ConfigPath) {
    if (-not (Test-Path $ConfigPath)) { return }
    $raw = [IO.File]::ReadAllText($ConfigPath)
    if ([string]::IsNullOrWhiteSpace($raw)) { return }
    $config = $raw | ConvertFrom-Json
    if (-not ($config.mcpServers -and $config.mcpServers.PSObject.Properties["onedrive"])) { return }
    Copy-Item $ConfigPath "$ConfigPath.bak" -Force
    $config.mcpServers.PSObject.Properties.Remove("onedrive")
    $json = $config | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($ConfigPath, $json, (New-Object Text.UTF8Encoding $false))
    Write-Host "Entrée retirée de $ConfigPath"
}

try {
    foreach ($path in Get-ClaudeConfigPaths) { Remove-ClaudeEntry $path }
    Wait-ServerStopped $InstallDir

    $tokenDir = Join-Path $env:USERPROFILE ".config\onedrive-mcp"
    foreach ($dir in @($tokenDir, $InstallDir)) {
        if (Test-Path $dir) {
            Remove-Item $dir -Recurse -Force
            Write-Host "Supprimé : $dir"
        }
    }
    Write-Host "Désinstallation terminée. Quitte puis relance Claude Desktop." -ForegroundColor Green
    exit 0
} catch {
    Write-Host "ERREUR : $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
