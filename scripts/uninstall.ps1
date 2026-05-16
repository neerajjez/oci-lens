#Requires -Version 5.1
<#
.SYNOPSIS
    Uninstall OCI Cloud Cost Optimizer from Windows.
.PARAMETER Purge
    Also remove the venv/ directory and reports/ directory (config is preserved).
#>

param(
    [switch]$Purge
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$WORK_DIR   = Split-Path -Parent $SCRIPT_DIR
$PYEX       = Join-Path $WORK_DIR 'venv' 'Scripts' 'python.exe'

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

Write-Step "Removing Task Scheduler entry"
$schedScript = Join-Path $WORK_DIR 'scripts' 'setup_schedule.py'
if (Test-Path $PYEX) {
    try {
        & $PYEX $schedScript uninstall
    } catch {
        Write-Host "  Could not remove task (may not be installed): $_" -ForegroundColor Yellow
    }
} else {
    try {
        schtasks /Delete /TN OCICostOptimizer /F 2>$null
        Write-Host "  Task removed."
    } catch {
        Write-Host "  Task not found or already removed." -ForegroundColor Yellow
    }
}

if ($Purge) {
    Write-Step "Purging venv and reports (config preserved)"
    $venv = Join-Path $WORK_DIR 'venv'
    if (Test-Path $venv) {
        Remove-Item $venv -Recurse -Force
        Write-Host "  Removed: $venv"
    }
    $reports = Join-Path $WORK_DIR 'reports'
    if (Test-Path $reports) {
        Remove-Item $reports -Recurse -Force
        Write-Host "  Removed: $reports"
    }
}

Write-Host "`nUninstall complete." -ForegroundColor Green
if (-not $Purge) {
    Write-Host "  Re-run with -Purge to also remove venv/ and reports/."
}
