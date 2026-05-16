#Requires -Version 5.1
<#
.SYNOPSIS
    Install OCI Cloud Cost Optimizer on Windows.
.DESCRIPTION
    Detects Python 3.9+, creates a virtual environment, installs dependencies,
    copies config examples, validates configuration, and optionally sets up
    the Task Scheduler entry.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$WORK_DIR   = Split-Path -Parent $SCRIPT_DIR

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Find-Python {
    foreach ($cmd in @('py', 'python', 'python3')) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match 'Python (\d+)\.(\d+)') {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -ge 3 -and $minor -ge 9) {
                    return $cmd
                }
            }
        } catch { }
    }
    return $null
}

Write-Step "Checking Python version"
$PYTHON = Find-Python
if (-not $PYTHON) {
    Write-Error "Python 3.9 or newer is required but was not found. Install from https://python.org"
    exit 1
}
$ver = & $PYTHON --version
Write-Host "Found: $ver ($PYTHON)"

Set-Location $WORK_DIR

Write-Step "Creating virtual environment"
$VENV = Join-Path $WORK_DIR 'venv'
if (-not (Test-Path $VENV)) {
    & $PYTHON -m venv $VENV
}
$PIP  = Join-Path $VENV 'Scripts' 'pip.exe'
$PYEX = Join-Path $VENV 'Scripts' 'python.exe'

Write-Step "Installing dependencies"
& $PIP install --upgrade pip --quiet
& $PIP install -r (Join-Path $WORK_DIR 'requirements.txt') --quiet

Write-Step "Copying example config files"
$CONFIG_DIR = Join-Path $WORK_DIR 'config'
foreach ($example in Get-ChildItem $CONFIG_DIR -Filter '*.example') {
    $dest = Join-Path $CONFIG_DIR ($example.Name -replace '\.example$', '')
    if (-not (Test-Path $dest)) {
        Copy-Item $example.FullName $dest
        Write-Host "  Created: $dest"
    }
}

Write-Step "Validating configuration"
try {
    & $PYEX (Join-Path $WORK_DIR 'main.py') validate-config
} catch {
    Write-Host "  Config validation failed -- edit config/config.yaml before running." -ForegroundColor Yellow
}

$answer = Read-Host "`nInstall Task Scheduler entry to run every 15 days? [y/N]"
if ($answer -match '^[Yy]') {
    Write-Step "Installing Task Scheduler entry"
    & $PYEX (Join-Path $WORK_DIR 'scripts' 'setup_schedule.py') install
}

Write-Host "`nInstallation complete." -ForegroundColor Green
Write-Host "  Activate venv : venv\Scripts\Activate.ps1"
Write-Host "  Run report    : python main.py run"
Write-Host "  Dry run       : python main.py run --dry-run"
