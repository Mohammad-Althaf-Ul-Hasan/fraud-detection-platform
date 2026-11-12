# run_demo.ps1 — hardened Phase 2 demo
$ErrorActionPreference = "Stop"
$ProjectRoot = "C:\Users\Mohammad Althaf\Desktop\fraud-detection"
$ApiBase = "http://127.0.0.1:8000"
Set-Location $ProjectRoot

Write-Host "=== 0. Killing any process on port 8000 ===" -ForegroundColor Cyan
$existing = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    foreach ($procId in ($existing.OwningProcess | Sort-Object -Unique)) {
        Write-Host "  Killing PID $procId"
        taskkill /PID $procId /T /F 2>$null | Out-Null
    }
    Start-Sleep -Seconds 2
} else {
    Write-Host "  Port 8000 already free"
}

Write-Host "=== 1. Checking Docker ===" -ForegroundColor Cyan
$ps = docker compose ps --format "{{.Name}} {{.Status}}"
if ($ps -notmatch "fraud-kafka.*running" -or $ps -notmatch "fraud-redis.*running") {
    Write-Host "  Starting containers ..." -ForegroundColor Yellow
    docker compose up -d
    Start-Sleep -Seconds 10
}

Write-Host "=== 2. Verifying Kafka ===" -ForegroundColor Cyan
if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 9092 -InformationLevel Quiet)) {
    Write-Host "  Kafka NOT reachable on 9092. Exiting." -ForegroundColor Red
    exit 1
}
Write-Host "  Kafka reachable" -ForegroundColor Green

Write-Host "=== 3. Starting scoring service (new window) ===" -ForegroundColor Cyan
$serviceProc = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ProjectRoot'; .venv\Scripts\activate; uvicorn services.scoring_service:app --host 127.0.0.1 --port 8000" -PassThru
Write-Host "  Wrapper PID: $($serviceProc.Id)"
Write-Host "  If it fails, look at the OTHER PowerShell window." -ForegroundColor Yellow

Write-Host "=== 4. Waiting for /health ===" -ForegroundColor Cyan
$maxWait = 60
$elapsed = 0
$healthy = $false
while ($elapsed -lt $maxWait) {
    Start-Sleep -Seconds 2
    $elapsed += 2
    try {
        $h = Invoke-RestMethod "$ApiBase/health" -TimeoutSec 2
        if ($h.status -eq "ok") {
            Write-Host "  Healthy! threshold=$($h.threshold)" -ForegroundColor Green
            $healthy = $true
            break
        }
    } catch {
        Write-Host "  ... waiting ${elapsed}s"
    }
}

if (-not $healthy) {
    Write-Host "Service did not become healthy in $maxWait s." -ForegroundColor Red
    Write-Host "Check the OTHER PowerShell window (the one with uvicorn)." -ForegroundColor Yellow
    exit 1
}

Start-Sleep -Seconds 5

Write-Host "`n=== 5. Stats BEFORE producer ===" -ForegroundColor Cyan
Invoke-RestMethod "$ApiBase/stats" | ConvertTo-Json -Depth 4

Write-Host "`n=== 6. Producer: 5000 txns at 50 TPS ===" -ForegroundColor Cyan
python scripts\kafka_producer.py --tps 50 --limit 5000

Write-Host "`n=== 7. Waiting 15s for consumer drain ===" -ForegroundColor Cyan
Start-Sleep -Seconds 15

Write-Host "`n=== 8. Stats AFTER producer ===" -ForegroundColor Cyan
Invoke-RestMethod "$ApiBase/stats" | ConvertTo-Json -Depth 4

Write-Host "`n=== 9. Recent 3 ===" -ForegroundColor Cyan
Invoke-RestMethod "$ApiBase/recent?n=3" | ConvertTo-Json -Depth 4

Write-Host "`n=== 10. Benchmark ===" -ForegroundColor Cyan
python scripts\benchmark.py --n 300 --url "$ApiBase/predict"

Write-Host "`n=== Demo complete ===" -ForegroundColor Green
Write-Host "Service is still running in the other window." -ForegroundColor Yellow