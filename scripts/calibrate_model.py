"""Fit isotonic calibration on the XGBoost validation split.

Produces:
  models/calibrator.pkl         — sklearn IsotonicRegression instance
  models/calibrator_meta.json   — threshold, PR-AUCs, provenance

The scoring service loads both at startup and applies the calibrator
before soft-OR blend. Threshold is re-selected on calibrated scores at
best F1 on a holdout split that was not used for fitting.

Method:
  * 50/50 split of the validation set (step > warmup cutoff)
  * Fit IsotonicRegression on half A (raw_score, y)
  * Compute best-F1 threshold on half B (calibrated)
  * Log to MLflow with tag artifact_type=calibrator (excluded from /models)
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import mlflow
import mlflow.xgboost
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import precision_recall_curve, average_precision_score

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from common.schema import FEATURE_COLS  # noqa: E402

FEATURES_PARQUET = PROJECT_ROOT / "data" / "processed" / "features.parquet"
CUTOFF_FILE = PROJECT_ROOT / "data" / "processed" / "warmup_cutoff.txt"
MLFLOW_DB = PROJECT_ROOT / "mlflow.db"
MLFLOW_URI = f"sqlite:///{MLFLOW_DB.as_posix()}"
EXPERIMENT = "fraud-detection-paysim"

MODELS_DIR = PROJECT_ROOT / "models"
CALIBRATOR_PATH = MODELS_DIR / "calibrator.pkl"
META_PATH = MODELS_DIR / "calibrator_meta.json"

RANDOM_SEED = 42


def load_latest_xgb_run():
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.tracking.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT)
    if exp is None:
        raise SystemExit(f"MLflow experiment '{EXPERIMENT}' not found.")
    runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        order_by=["start_time DESC"],
    )
    xgb_runs = [r for r in runs if "pr_auc" in r.data.metrics]
    if not xgb_runs:
        raise SystemExit(f"No XGBoost runs with 'pr_auc' in '{EXPERIMENT}'.")
    run = xgb_runs[0]
    print(f"Selected parent run {run.info.run_id} (pr_auc={run.data.metrics['pr_auc']:.4f})")
    model = mlflow.xgboost.load_model(f"runs:/{run.info.run_id}/model")
    threshold_raw = float(run.data.metrics.get("best_threshold", 0.5))
    return model, run.info.run_id, threshold_raw


def main():
    if not FEATURES_PARQUET.exists():
        raise SystemExit(f"Missing {FEATURES_PARQUET}. Run Phase 1 first.")
    cutoff = int(CUTOFF_FILE.read_text().strip())
    print(f"Cutoff step = {cutoff}")

    model, parent_run_id, threshold_raw = load_latest_xgb_run()

    print(f"Loading features (step > {cutoff}) ...")
    val_df = pd.read_parquet(
        FEATURES_PARQUET,
        columns=FEATURE_COLS + ["step", "isFraud"],
        filters=[("step", ">", cutoff)],
    ).reset_index(drop=True)
    print(f"  validation rows: {len(val_df):,}")
    print(f"  fraud rate     : {val_df['isFraud'].mean()*100:.4f}%")

    X_val = val_df[FEATURE_COLS].values.astype(np.float32)
    y_val = val_df["isFraud"].values.astype(np.int8)

    print("Scoring validation set with parent model ...")
    raw_scores = model.predict_proba(X_val)[:, 1].astype(np.float64)
    print(f"  raw score range: [{raw_scores.min():.6f}, {raw_scores.max():.6f}]")

    rng = np.random.default_rng(RANDOM_SEED)
    perm = rng.permutation(len(raw_scores))
    n_cal = len(perm) // 2
    cal_idx, thr_idx = perm[:n_cal], perm[n_cal:]
    print(f"  calibration split: {len(cal_idx):,}  /  threshold split: {len(thr_idx):,}")

    print("Fitting isotonic regression ...")
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(raw_scores[cal_idx], y_val[cal_idx])

    print("Recomputing threshold on calibrated holdout ...")
    cal_scores_holdout = iso.predict(raw_scores[thr_idx])
    prec, rec, thresh = precision_recall_curve(y_val[thr_idx], cal_scores_holdout)
    f1s = 2 * prec * rec / (prec + rec + 1e-12)
    best_i = int(np.nanargmax(f1s))
    best_thr = float(thresh[best_i]) if best_i < len(thresh) else 0.5

    ap_cal = float(average_precision_score(y_val[thr_idx], cal_scores_holdout))
    ap_raw = float(average_precision_score(y_val[thr_idx], raw_scores[thr_idx]))

    print()
    print("=== Calibration results ===")
    print(f"  PR-AUC raw (holdout)        : {ap_raw:.4f}")
    print(f"  PR-AUC calibrated (holdout) : {ap_cal:.4f}")
    print(f"  threshold_raw               : {threshold_raw:.4f}")
    print(f"  threshold_calibrated        : {best_thr:.4f}")
    print(f"  precision @ best_thr        : {float(prec[best_i]):.4f}")
    print(f"  recall    @ best_thr        : {float(rec[best_i]):.4f}")
    print(f"  F1        @ best_thr        : {float(f1s[best_i]):.4f}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(iso, CALIBRATOR_PATH)
    print(f"\n  saved {CALIBRATOR_PATH.relative_to(PROJECT_ROOT)}")

    meta = {
        "method": "isotonic",
        "threshold_calibrated": best_thr,
        "threshold_raw": threshold_raw,
        "pr_auc_calibrated_holdout": ap_cal,
        "pr_auc_raw_holdout": ap_raw,
        "precision_at_best": float(prec[best_i]),
        "recall_at_best": float(rec[best_i]),
        "f1_at_best": float(f1s[best_i]),
        "parent_run_id": parent_run_id,
        "n_calibration_rows": int(len(cal_idx)),
        "n_threshold_rows": int(len(thr_idx)),
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  saved {META_PATH.relative_to(PROJECT_ROOT)}")

    print("\nLogging to MLflow ...")
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name="xgb_isotonic_calibration") as run:
        mlflow.set_tag("artifact_type", "calibrator")
        mlflow.set_tag("calibrated", "true")
        mlflow.log_param("method", "isotonic")
        mlflow.log_param("parent_run_id", parent_run_id)
        mlflow.log_metric("pr_auc_calibrated_holdout", ap_cal)
        mlflow.log_metric("pr_auc_raw_holdout", ap_raw)
        mlflow.log_metric("threshold_calibrated", best_thr)
        mlflow.log_metric("threshold_raw", threshold_raw)
        mlflow.log_artifact(str(CALIBRATOR_PATH))
        mlflow.log_artifact(str(META_PATH))
        print(f"  MLflow run: {run.info.run_id}")

    print("\nDone. Restart the backend to pick up the calibrated model.")


if __name__ == "__main__":
    main()