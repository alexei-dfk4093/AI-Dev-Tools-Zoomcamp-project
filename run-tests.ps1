# EcoMind one-command test run.
#
# Runs the backend (pytest) and frontend (vitest) suites together and
# exits non-zero when either fails. All external APIs are mocked, so the
# run is deterministic and costs nothing.
#
# Usage:
#   .\run-tests.ps1                 # run both suites
#   .\run-tests.ps1 -SkipFrontend  # backend only
#   .\run-tests.ps1 -SkipBackend   # frontend only
[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$failures = @()

if (-not $SkipBackend) {
    Write-Host ""
    Write-Host "==> Backend tests (pytest)" -ForegroundColor Cyan
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    $python = if (Test-Path $venvPython) { $venvPython } else { "python" }
    & $python -m pytest (Join-Path $root "backend\tests") -q
    if ($LASTEXITCODE -ne 0) {
        $failures += "backend"
        Write-Host "    Backend tests FAILED." -ForegroundColor Red
    }
    else {
        Write-Host "    Backend tests passed." -ForegroundColor Green
    }
}

if (-not $SkipFrontend) {
    Write-Host ""
    Write-Host "==> Frontend tests (vitest)" -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
        Write-Host "    Installing frontend dependencies (npm install)…"
        Push-Location (Join-Path $root "frontend")
        try { npm install --no-fund --no-audit }
        finally { Pop-Location }
    }
    Push-Location (Join-Path $root "frontend")
    try {
        npm run test
        if ($LASTEXITCODE -ne 0) {
            $failures += "frontend"
            Write-Host "    Frontend tests FAILED." -ForegroundColor Red
        }
        else {
            Write-Host "    Frontend tests passed." -ForegroundColor Green
        }
    }
    finally { Pop-Location }
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host ("Test run FAILED: " + ($failures -join ", ")) -ForegroundColor Red
    exit 1
}
Write-Host "Test run passed (backend + frontend)." -ForegroundColor Green
