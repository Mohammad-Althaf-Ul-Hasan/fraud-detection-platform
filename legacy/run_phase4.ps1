# run_phase4.ps1
$ErrorActionPreference = "Stop"

Write-Host "=== Phase 4 Orchestrator (Evidently Drift + Retrain Trigger) ===" -ForegroundColor Cyan

Write-Host "`n[0] Verify Evidently installed ..." -ForegroundColor Yellow
python -c "from evidently.report import Report; from evidently.metric_preset import DataDriftPreset; print('evidently OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Installing evidently ..." -ForegroundColor Gray
    pip install "evidently>=0.4.0,<0.7"
    if ($LASTEXITCODE -ne 0) { Write-Host "Install failed." -ForegroundColor Red; exit 1 }
}

Write-Host "`n[1] Verifying Docker + service ..." -ForegroundColor Yellow
docker compose ps | Out-Null
$health = $null
try {
    $health = Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 3
} catch {
    Write-Host "  Service not running - starting it ..." -ForegroundColor Gray
    $port = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
    if ($port) { $port | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }
    Start-Sleep 2
    $cwd = (Get-Location).Path
    Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$cwd'; .\.venv\Scripts\Activate; uvicorn services.scoring_service:app --host 127.0.0.1 --port 8000"
    $ok = $false
    for ($i=1; $i -le 30; $i++) {
        Start-Sleep 1
        try { $health = Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 2
              if ($health.status -eq "ok") { $ok = $true; break } } catch {}
    }
    if (-not $ok) { Write-Host "Service did not come up." -ForegroundColor Red; exit 1 }
}
Write-Host "  service healthy  threshold=$($health.threshold)  buffer=$($health.feature_buffer_size)"

Write-Host "`n[2] Ensuring feature buffer has data ..." -ForegroundColor Yellow
$buf = (Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 3).feature_buffer_size
if ($buf -lt 1000) {
    Write-Host "  buffer has $buf rows - replaying 2000 txns @ 100 TPS ..." -ForegroundColor Gray
    python scripts\kafka_producer.py --tps 100 --limit 2000
    Start-Sleep 5
    $buf = (Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 3).feature_buffer_size
}
Write-Host "  buffer size: $buf"

Write-Host "`n[3] Drift check (natural continuation of training data) ..." -ForegroundColor Yellow
python scripts\drift_monitor.py

Write-Host "`n[4] /drift endpoint (natural) ..." -ForegroundColor Yellow
Invoke-RestMethod http://127.0.0.1:8000/drift | ConvertTo-Json -Depth 5

Write-Host "`n[5] Drift check (simulated shift on 20 columns) ..." -ForegroundColor Yellow
python scripts\drift_monitor.py --simulate-drift

Write-Host "`n[6] /drift endpoint (simulated) ..." -ForegroundColor Yellow
Invoke-RestMethod http://127.0.0.1:8000/drift | ConvertTo-Json -Depth 5

Write-Host "`n[7] Retrain trigger dry-run (simulated drift is active) ..." -ForegroundColor Yellow
python scripts\retrain_trigger.py --dry-run

Write-Host "`n=== Phase 4 complete ===" -ForegroundColor Green
Write-Host "Reports directory: reports"
Write-Host "  drift_<ts>.html   - open in browser for full report"
Write-Host "  latest_drift.json - what /drift serves"
Write-Host "  retrain_log.jsonl - decision audit trail"
Write-Host ""
Write-Host "To actually retrain (takes ~3-5 min):"
Write-Host "  python scripts\retrain_trigger.py --auto-reload"