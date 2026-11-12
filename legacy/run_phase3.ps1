# run_phase3.ps1
$ErrorActionPreference = "Stop"

Write-Host "=== Phase 3 Orchestrator ===" -ForegroundColor Cyan

Write-Host "`n[0] Verify PyG ..." -ForegroundColor Yellow
python scripts\verify_pyg.py
if ($LASTEXITCODE -ne 0) { Write-Host "PyG broken. Stop." -ForegroundColor Red; exit 1 }

Write-Host "`n[1] Build graph ..." -ForegroundColor Yellow
python scripts\build_graph.py
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`n[2] Train GNN ..." -ForegroundColor Yellow
python scripts\train_gnn.py
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`n[3] Export embeddings to Redis ..." -ForegroundColor Yellow
python scripts\export_gnn_embeddings.py
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`n[4] Restart scoring service ..." -ForegroundColor Yellow
$port = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($port) {
    $port | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep 2
}
$cwd = (Get-Location).Path
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$cwd'; .\.venv\Scripts\Activate; uvicorn services.scoring_service:app --host 127.0.0.1 --port 8000"

Write-Host "  waiting for /health ..." -ForegroundColor Gray
$ok = $false
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep 1
    try {
        $h = Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 2
        if ($h.status -eq "ok") { $ok = $true; Write-Host "  Healthy!" -ForegroundColor Green; break }
    } catch {}
}
if (-not $ok) { Write-Host "  Service did not come up." -ForegroundColor Red; exit 1 }

Write-Host "`n[5] Replay 5000 txns @ 50 TPS ..." -ForegroundColor Yellow
python scripts\kafka_producer.py --tps 50 --limit 5000

Write-Host "`n[6] Waiting 15s for drain ..." -ForegroundColor Yellow
Start-Sleep 15

Write-Host "`n[7] Stats ..." -ForegroundColor Yellow
Invoke-RestMethod http://127.0.0.1:8000/stats | ConvertTo-Json -Depth 4

Write-Host "`n[8] Sample /graph on a ring member ..." -ForegroundColor Yellow
$ringAccount = python -c "import pandas as pd; df = pd.read_parquet('data/processed/features_with_rings.parquet', columns=['nameOrig','is_ring_member']); print(df[df['is_ring_member']==1]['nameOrig'].iloc[0])"
Write-Host "  account: $ringAccount"
Invoke-RestMethod "http://127.0.0.1:8000/graph/$ringAccount" | ConvertTo-Json -Depth 4

Write-Host "`n=== Phase 3 complete ===" -ForegroundColor Green
Write-Host "Service still running on 127.0.0.1:8000"