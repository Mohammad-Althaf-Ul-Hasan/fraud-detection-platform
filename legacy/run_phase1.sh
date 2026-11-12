#!/usr/bin/env bash
set -euo pipefail

echo ">>> [1/4] Loading PaySim"
python scripts/load_data.py

echo ">>> [2/4] Running EDA"
python scripts/eda.py

echo ">>> [3/4] Computing features"
python scripts/compute_features.py

echo ">>> [4/4] Training XGBoost + logging to MLflow"
python scripts/train_xgb.py

echo
echo "Phase 1 complete."
echo "  EDA plots  → data/processed/eda/"
echo "  Features   → data/processed/features.parquet"
echo "  MLflow     → mlruns/  (run: mlflow ui --backend-store-uri file:./mlruns)"
echo
echo "Next: register Feast features"
echo "  cd feature_repo && feast apply && feast materialize-incremental \$(date -u +%Y-%m-%dT%H:%M:%S)"