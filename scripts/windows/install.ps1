<#
.SYNOPSIS
    Installe le serveur MCP OneDrive pour Claude Desktop (Windows).

.DESCRIPTION
    1. installe uv (gestionnaire Python), puis Python 3.12
    2. copie le projet dans %LOCALAPPDATA%\onedrive-mcp
    3. installe les dependances
    4. connecte ton compte Microsoft (le navigateur s'ouvre)
    5. ajoute le serveur "onedrive" a la config de Claude Desktop
       (les autres serveurs deja configures sont conserves)

    Relancable sans risque : chaque etape deja faite est sautee ou rafraichie.
#>
param(
    [string]$ClientId = "9a9b2062-3a4c-4b63-a4b1-c0ec74683494",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "onedrive-mcp")
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ExitNotSignedIn = 3
# scripts\windows\install.ps1 -> racine du projet deux niveaux au-dessus
$SourceDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot "common.ps1")

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    # uv et onedrive-mcp écrivent leurs messages sur stderr : sous PowerShell 5.1
    # et "Stop", cela peut devenir une erreur fatale. Seul le code de retour compte.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # Out-Host : l'affichage va à la console, pas dans la valeur de retour.
        & $Exe @Arguments | Out-Host
    } finally {
        $ErrorActionPreference = $previous
    }
    return $LASTEXITCODE
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    $code = Invoke-Native $Exe $Arguments
    if ($code -ne 0) {
        throw "La commande a échoué (code $code) : $Exe $($Arguments -join ' ')"
    }
}

function Get-UvPath {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Install-Uv {
    $uv = Get-UvPath
    if ($uv) {
        Write-Host "uv est déjà installé : $uv"
        return $uv
    }
    Write-Host "Téléchargement de l'installeur officiel de uv (astral.sh)..."
    # Processus séparé : l'installeur ne peut pas interrompre ce script.
    $command = "[Net.ServicePointManager]::SecurityProtocol = " +
        "[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; " +
        "irm https://astral.sh/uv/install.ps1 | iex"
    Invoke-Checked "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command)
    $uv = Get-UvPath
    if (-not $uv) { throw "uv reste introuvable après son installation." }
    return $uv
}

function Copy-Project([string]$From, [string]$To) {
    if (-not (Test-Path (Join-Path $From "pyproject.toml"))) {
        throw "Projet introuvable dans $From. Garde install.bat dans scripts\windows du projet."
    }
    $fromFull = [IO.Path]::GetFullPath($From).TrimEnd('\')
    $toFull = [IO.Path]::GetFullPath($To).TrimEnd('\')
    if ($fromFull -eq $toFull) {
        Write-Host "Le projet est déjà à sa place : $To"
        return
    }
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    robocopy $From $To /MIR /XD .venv .git __pycache__ .pytest_cache .ruff_cache /XF .env /NFL /NDL /NJH /NJS /NP | Out-Null
    # robocopy : un code < 8 signifie succès (avec ou sans fichiers copiés)
    if ($LASTEXITCODE -ge 8) { throw "La copie du projet a échoué (robocopy code $LASTEXITCODE)." }
    Write-Host "Projet copié dans $To"
}

function Connect-OneDrive([string]$ServerExe) {
    $code = Invoke-Native $ServerExe @("status")
    if ($code -eq 0) { return }
    if ($code -ne $ExitNotSignedIn) {
        throw "Impossible de vérifier la connexion OneDrive (code $code)."
    }
    Write-Host ""
    Write-Host "Une page Microsoft va s'ouvrir dans ton navigateur." -ForegroundColor Yellow
    Write-Host "Saisis le code affiché ci-dessous, puis connecte-toi avec le compte Microsoft du OneDrive." -ForegroundColor Yellow
    Invoke-Checked $ServerExe @("login", "--open-browser")
}

function Register-ClaudeDesktop([string]$ConfigPath, [string]$ServerExe, [string]$Id) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ConfigPath) | Out-Null
    $raw = ""
    if (Test-Path $ConfigPath) {
        $raw = [IO.File]::ReadAllText($ConfigPath)
        Copy-Item $ConfigPath "$ConfigPath.bak" -Force
    }
    if ([string]::IsNullOrWhiteSpace($raw)) {
        $config = New-Object PSObject
    } else {
        $config = $raw | ConvertFrom-Json
    }
    if (-not $config.PSObject.Properties["mcpServers"]) {
        $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue (New-Object PSObject)
    }
    $server = [pscustomobject]@{
        command = $ServerExe
        args    = @("serve")
        env     = [pscustomobject]@{ ONEDRIVE_CLIENT_ID = $Id }
    }
    $config.mcpServers | Add-Member -NotePropertyName onedrive -NotePropertyValue $server -Force
    $json = $config | ConvertTo-Json -Depth 20
    # UTF-8 sans BOM : un BOM peut empêcher Claude Desktop de lire le fichier.
    [IO.File]::WriteAllText($ConfigPath, $json, (New-Object Text.UTF8Encoding $false))
    Write-Host "Config mise à jour : $ConfigPath"
}

function Install-OneDriveMcp {
    if ($env:OS -ne "Windows_NT") { throw "Ce script est prévu pour Windows." }

    Write-Step "1/5  uv et Python"
    $uv = Install-Uv
    Invoke-Checked $uv @("python", "install", "3.12")

    Write-Step "2/5  Copie du projet"
    Wait-ServerStopped $InstallDir
    Copy-Project $SourceDir $InstallDir

    Write-Step "3/5  Dépendances"
    Invoke-Checked $uv @("--directory", $InstallDir, "sync", "--frozen", "--no-dev", "--python", "3.12")
    $serverExe = Join-Path $InstallDir ".venv\Scripts\onedrive-mcp.exe"
    if (-not (Test-Path $serverExe)) { throw "Exécutable introuvable : $serverExe" }

    Write-Step "4/5  Connexion OneDrive"
    $env:ONEDRIVE_CLIENT_ID = $ClientId
    Connect-OneDrive $serverExe

    Write-Step "5/5  Claude Desktop"
    foreach ($path in Get-ClaudeConfigPaths) {
        Register-ClaudeDesktop $path $serverExe $ClientId
    }

    Write-Host ""
    Write-Host "Installation terminée." -ForegroundColor Green
    Write-Host "Quitte complètement Claude Desktop (icône près de l'horloge > Quitter), puis relance-le."
    Write-Host "Vérification : Paramètres > Developer, 'onedrive' doit être 'running'."
}

try {
    Install-OneDriveMcp
    exit 0
} catch {
    Write-Host ""
    Write-Host "ERREUR : $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
