# Fonctions partagées par install.ps1 et uninstall.ps1 (chargé par dot-sourcing).

function Get-ClaudeConfigPaths {
    $paths = @(Join-Path $env:APPDATA "Claude\claude_desktop_config.json")
    # Version Microsoft Store : la config vit dans le dossier virtualisé du package.
    $packages = Join-Path $env:LOCALAPPDATA "Packages"
    if (Test-Path $packages) {
        foreach ($package in @(Get-ChildItem $packages -Directory -Filter "*Claude*" -ErrorAction SilentlyContinue)) {
            $dir = Join-Path $package.FullName "LocalCache\Roaming\Claude"
            if (Test-Path $dir) { $paths += (Join-Path $dir "claude_desktop_config.json") }
        }
    }
    return $paths
}

function Get-ServerProcesses([string]$InstallDir) {
    # Processus lancés depuis le dossier d'installation (onedrive-mcp.exe, python.exe).
    $prefix = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\') + '\'
    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    })
}

function Wait-ServerStopped([string]$InstallDir) {
    # Tant que Claude Desktop fait tourner le serveur, ses fichiers sont verrouillés.
    while ((Get-ServerProcesses $InstallDir).Count -gt 0) {
        Write-Host ""
        Write-Host "Claude Desktop utilise encore le serveur OneDrive." -ForegroundColor Yellow
        Write-Host "Quitte complètement Claude Desktop (icône près de l'horloge > Quitter)."
        Read-Host "Puis appuie sur Entrée pour continuer" | Out-Null
    }
}
