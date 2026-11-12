# EcoMind one-command local startup.
#
# Starts the complete application end to end with one command:
#   - backend:  FastAPI API + SQLite persistent storage (port 8000)
#   - frontend: Vite dev server (port 5173, proxies /api to the backend)
# The backend loads its configuration (NEWS_API_KEY, OPENROUTER_API_KEY)
# from the project-root .env file.
#
# Usage:
#   .\start.ps1           # start everything and open the browser
#   .\start.ps1 -NoOpen   # start without opening the browser
# Press Ctrl+C (or exit a server) to stop both.
[CmdletBinding()]
param(
    [switch]$NoOpen,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = $null
$frontend = $null

function Test-PortListening([int]$Port) {
    return $null -ne (
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    )
}

function Wait-ForHttp([string]$Url, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
            return $true
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Stop-ProcessTree($Process) {
    if ($Process -and -not $Process.HasExited) {
        $previousEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try { taskkill /PID $Process.Id /T /F 2>$null | Out-Null }
        catch { }
        finally { $ErrorActionPreference = $previousEap }
    }
}

try {
    # --- 1. Backend environment: virtualenv + dependencies -----------------
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "==> Creating Python virtual environment (.venv)…"
        python -m venv (Join-Path $root ".venv")
        & $venvPython -m pip install --quiet --disable-pip-version-check `
            -r (Join-Path $root "backend\requirements.txt")
    }
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $venvPython -c "import fastapi, uvicorn, dotenv, httpx" 2>$null
    $depsInstalled = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previousEap
    if (-not $depsInstalled) {
        Write-Host "==> Installing backend dependencies…"
        & $venvPython -m pip install --quiet --disable-pip-version-check `
            -r (Join-Path $root "backend\requirements.txt")
    }

    # --- 2. Configuration check --------------------------------------------
    if (-not (Test-Path (Join-Path $root ".env"))) {
        Write-Warning "No .env file found at the project root. Copy .env.example " +
            "and set NEWS_API_KEY (and OPENROUTER_API_KEY for AI features)."
    }

    # --- 3. Frontend environment: node_modules ------------------------------
    if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
        Write-Host "==> Installing frontend dependencies (npm install)…"
        Push-Location (Join-Path $root "frontend")
        try { npm install --no-fund --no-audit }
        finally { Pop-Location }
    }

    # --- 4. Backend ----------------------------------------------------------
    if (Test-PortListening $BackendPort) {
        Write-Host "==> Port $BackendPort is already serving; reusing the running backend."
    }
    else {
        Write-Host "==> Starting backend (FastAPI + SQLite) on http://127.0.0.1:$BackendPort …"
        $backendAppDir = Join-Path $root "backend"
        $backend = Start-Process -FilePath $venvPython `
            -ArgumentList "-m", "uvicorn", "app.main:app", `
                "--app-dir", "`"$backendAppDir`"", `
                "--host", "127.0.0.1", "--port", "$BackendPort" `
            -WorkingDirectory $root -NoNewWindow -PassThru
        $deadline = (Get-Date).AddSeconds(60)
        while (-not $backend.HasExited -and (Get-Date) -lt $deadline) {
            try {
                Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/health" `
                    -UseBasicParsing -TimeoutSec 2 | Out-Null
                break
            }
            catch {
                Start-Sleep -Milliseconds 500
            }
        }
        if ($backend.HasExited) {
            throw "The backend process exited during startup. Check the output above."
        }
        if (-not (Test-PortListening $BackendPort)) {
            throw "Backend did not become healthy within 60 seconds. Check the output above."
        }
        Write-Host "    Backend healthy (data: backend\data\economind.db)."
    }

    # --- 5. Frontend ----------------------------------------------------------
    if (Test-PortListening $FrontendPort) {
        Write-Host "==> Port $FrontendPort is already serving; reusing the running frontend."
    }
    else {
        Write-Host "==> Starting frontend (Vite) on http://localhost:$FrontendPort …"
        $viteJs = Join-Path $root "frontend\node_modules\vite\bin\vite.js"
        $frontend = Start-Process -FilePath "node" `
            -ArgumentList "`"$viteJs`"", "--port", "$FrontendPort", "--strictPort" `
            -WorkingDirectory (Join-Path $root "frontend") -NoNewWindow -PassThru
        if (-not (Wait-ForHttp "http://localhost:$FrontendPort" 60)) {
            throw "Frontend did not start within 60 seconds. Check the output above."
        }
        Write-Host "    Frontend serving."
    }

    # --- 6. Ready ---------------------------------------------------------------
    Write-Host ""
    Write-Host "EcoMind is running:" -ForegroundColor Green
    Write-Host "  App:      http://localhost:$FrontendPort"
    Write-Host "  API docs: http://127.0.0.1:$BackendPort/docs"
    Write-Host "Press Ctrl+C to stop."

    if (-not $NoOpen) {
        try { Start-Process "http://localhost:$FrontendPort" | Out-Null }
        catch { Write-Warning "Could not open a browser automatically: $($_.Exception.Message)" }
    }

    # Stay in the foreground while the servers run.
    while ($true) {
        if ($backend -and $backend.HasExited) {
            Write-Warning "The backend process exited."
            break
        }
        if ($frontend -and $frontend.HasExited) {
            Write-Warning "The frontend process exited."
            break
        }
        Start-Sleep -Seconds 2
    }
}
finally {
    Write-Host ""
    Write-Host "==> Stopping EcoMind servers…"
    Stop-ProcessTree $backend
    Stop-ProcessTree $frontend
    Write-Host "    Stopped."
}
