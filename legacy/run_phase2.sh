#!/usr/bin/env bash
set -euo pipefail

echo ">>> [1/6] Bringing up Kafka + Redis"
docker compose up -d
sleep 8   # let Kafka broker finish startup

echo ">>> [2/6] Feast: re-apply with Redis online store"
pushd feature_repo > /dev/null
feast apply
popd > /dev/null

echo ">>> [3/6] Materializing warmup window to Redis"
python scripts/materialize_warmup.py

echo ">>> [4/6] Starting FastAPI scoring service in background"
uvicorn services.scoring_service:app --host 0.0.0.0 --port 8000 &
SERVICE_PID=$!
trap "kill $SERVICE_PID 2>/dev/null || true" EXIT

# Wait for health
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health | grep -q '"status":"ok"'; then
    echo "    Service healthy."
    break
  fi
  sleep 1
done

echo ">>> [5/6] Replaying 5000 transactions at 50 TPS"
python scripts/kafka_producer.py --tps 50 --limit 5000

echo "    Waiting 5s for consumer to drain ..."
sleep 5

echo ">>> [6/6] Stats and benchmark"
echo
echo "--- /stats ---"
curl -s http://localhost:8000/stats | python -m json.tool
echo
echo "--- /predict latency ---"
python scripts/benchmark.py --n 300

echo
echo "Phase 2 complete. Service is running on :8000"
echo "  Press Ctrl+C to stop, or: kill $SERVICE_PID"
wait $SERVICE_PID