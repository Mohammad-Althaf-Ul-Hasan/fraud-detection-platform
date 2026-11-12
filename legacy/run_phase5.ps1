# run_phase5.ps1 - ASCII only, no unicode punctuation
$ErrorActionPreference = "Stop"

Write-Host "=== Phase 5 Orchestrator (React Dashboard) ===" -ForegroundColor Cyan

Write-Host "`n[0] Checking Node.js ..." -ForegroundColor Yellow
try {
    $nodeVersion = node --version
    Write-Host "  node $nodeVersion"
} catch {
    Write-Host "  ERROR: Node.js not installed. Install from https://nodejs.org/" -ForegroundColor Red
    exit 1
}
try {
    $npmVersion = npm --version
    Write-Host "  npm $npmVersion"
} catch {
    Write-Host "  ERROR: npm not installed." -ForegroundColor Red
    exit 1
}

Write-Host "`n[1] Verifying backend is running ..." -ForegroundColor Yellow
$ok = $false
$h = $null
for ($i = 1; $i -le 10; $i++) {
    try {
        $h = Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 2
        if ($h.status -eq "ok") { $ok = $true; break }
    } catch { Start-Sleep 1 }
}
if (-not $ok) {
    Write-Host "  Backend not responding. Start it first:" -ForegroundColor Red
    Write-Host "    uvicorn services.scoring_service:app --host 127.0.0.1 --port 8000"
    exit 1
}
Write-Host "  Backend healthy (model_run_id=$($h.model_run_id))"

Write-Host "`n[2] Verifying new endpoints (/explain, /rings) ..." -ForegroundColor Yellow
$ringsOk = $false
try {
    $rings = Invoke-RestMethod http://127.0.0.1:8000/rings -TimeoutSec 15
    Write-Host "  /rings: $($rings.ring_count) rings"
    $ringsOk = $true
} catch {
    Write-Host "  ERROR: /rings failed: $($_.Exception.Message)" -ForegroundColor Red
}
if (-not $ringsOk) {
    Write-Host "  Aborting: restart the backend before running Phase 5 frontend." -ForegroundColor Red
    exit 1
}

Write-Host "`n[3] Installing frontend deps ..." -ForegroundColor Yellow
Push-Location frontend
try {
    if (-not (Test-Path "node_modules")) {
        Write-Host "  npm install (this may take 30-60 seconds) ..."
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
    } else {
        Write-Host "  node_modules present, skipping install"
    }

    Write-Host "`n[4] Starting Vite dev server ..." -ForegroundColor Yellow
    Write-Host "  Open this URL in your browser: http://127.0.0.1:5173" -ForegroundColor Green
    Write-Host "  Press Ctrl+C to stop." -ForegroundColor Gray
    npm run dev
} finally {
    Pop-Location
}