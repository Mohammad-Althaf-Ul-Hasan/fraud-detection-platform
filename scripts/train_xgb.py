"""Train XGBoost with class imbalance handled by scale_pos_weight.
Evaluate using PR-AUC (average precision) and time-based split.
Log everything to MLflow."""
from pathlib import Path
import numpy as np
import pandas as pd
import mlflow
import mlflow.xgboost
import xgboost as xgb
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.schema import FEATURE_COLS
from sklearn.metrics import (
    average_precision_score,
    roc_auc_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    f1_score,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PARQUET = PROJECT_ROOT / "data" / "processed" / "features.parquet"
MLFLOW_DB = PROJECT_ROOT / "mlflow.db"
MLFLOW_URI = f"sqlite:///{MLFLOW_DB.as_posix()}"
EXPERIMENT = "fraud-detection-paysim"

# FEATURE_COLS imported from common.schema above (removed leaky hardcoded list)


def time_split(df: pd.DataFrame, train_frac: float = 0.8):
    df = df.sort_values("step").reset_index(drop=True)
    cut = int(len(df) * train_frac)
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def main():
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT)

    print(f"Loading {FEATURES_PARQUET}")
    df = pd.read_parquet(FEATURES_PARQUET)

    train_df, val_df = time_split(df)
    print(f"Train: {len(train_df):,}  "
          f"(fraud={train_df['isFraud'].mean()*100:.3f}%)")
    print(f"Val:   {len(val_df):,}  "
          f"(fraud={val_df['isFraud'].mean()*100:.3f}%)")

    X_tr, y_tr = train_df[FEATURE_COLS], train_df["isFraud"]
    X_va, y_va = val_df[FEATURE_COLS], val_df["isFraud"]

    pos_weight = float((y_tr == 0).sum() / max((y_tr == 1).sum(), 1))
    print(f"scale_pos_weight = {pos_weight:.2f}")

    params = {
        "objective": "binary:logistic",
        "eval_metric": "aucpr",
        "tree_method": "hist",
        "max_depth": 6,
        "learning_rate": 0.08,
        "n_estimators": 400,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "min_child_weight": 3,
        "scale_pos_weight": pos_weight,
        "random_state": 42,
    }

    with mlflow.start_run(run_name="xgb_baseline_scale_pos_weight"):
        mlflow.log_params(params)
        mlflow.log_param("n_train", len(train_df))
        mlflow.log_param("n_val", len(val_df))
        mlflow.log_param("fraud_rate_train", float(y_tr.mean()))
        mlflow.log_param("fraud_rate_val", float(y_va.mean()))
        mlflow.log_param("feature_count", len(FEATURE_COLS))

        model = xgb.XGBClassifier(**params)
        model.fit(
            X_tr, y_tr,
            eval_set=[(X_va, y_va)],
            verbose=False,
        )

        proba = model.predict_proba(X_va)[:, 1]

        pr_auc = average_precision_score(y_va, proba)
        roc_auc = roc_auc_score(y_va, proba)

        precisions, recalls, thresholds = precision_recall_curve(y_va, proba)
        f1s = 2 * precisions * recalls / (precisions + recalls + 1e-12)
        best_i = int(np.nanargmax(f1s))
        best_thr = float(thresholds[best_i]) if best_i < len(thresholds) else 0.5

        y_hat = (proba >= best_thr).astype(int)
        prec = precision_score(y_va, y_hat, zero_division=0)
        rec = recall_score(y_va, y_hat, zero_division=0)
        f1 = f1_score(y_va, y_hat, zero_division=0)

        metrics = {
            "pr_auc": pr_auc,
            "roc_auc": roc_auc,
            "best_threshold": best_thr,
            "precision_at_best": prec,
            "recall_at_best": rec,
            "f1_at_best": f1,
        }
        mlflow.log_metrics(metrics)

        # Feature importance (top 15)
        imp = pd.Series(model.feature_importances_, index=FEATURE_COLS)
        imp = imp.sort_values(ascending=False)
        mlflow.log_dict(imp.head(15).round(5).to_dict(), "feature_importance_top15.json")

        mlflow.xgboost.log_model(model, artifact_path="model")

        print("\n=== Validation metrics ===")
        for k, v in metrics.items():
            print(f"  {k:22s}: {v:.4f}")

        print("\nTop 10 features by importance:")
        print(imp.head(10).round(4).to_string())

        print(f"\nMLflow run stored under {MLFLOW_URI}")


if __name__ == "__main__":
    main()