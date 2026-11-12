"""Run Evidently DataDriftPreset comparing training features to live features.

Reference: training split (step <= cutoff), sampled from features.parquet
Current:   live feature rows from GET /sample_features on the scoring service

Outputs:
  reports/drift_<timestamp>.json    full Evidently report as dict
  reports/drift_<timestamp>.html    full Evidently report as HTML
  reports/latest_drift.json         summary for the /drift endpoint
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from common.schema import (  # noqa: E402
    FEATURE_COLS,
    DRIFT_REPORT_DIR, DRIFT_REFERENCE_CACHE, DRIFT_LATEST_JSON,
    DRIFT_REFERENCE_SAMPLE_N, DRIFT_CURRENT_SAMPLE_N,
)

try:
    from evidently.report import Report
    from evidently.metric_preset import DataDriftPreset
except ImportError as e:
    raise SystemExit(
        "Evidently not installed (or wrong version).\n"
        "Fix: pip install \"evidently>=0.4.0,<0.7\"\n"
        f"Original error: {e}"
    )

FEATURES_PARQUET = PROJECT_ROOT / "data" / "processed" / "features.parquet"
CUTOFF_FILE      = PROJECT_ROOT / "data" / "processed" / "warmup_cutoff.txt"
SERVICE_URL      = "http://127.0.0.1:8000"


def build_reference_sample(force_rebuild: bool = False) -> pd.DataFrame:
    """20k rows from the training split. Cached to disk."""
    cache = PROJECT_ROOT / DRIFT_REFERENCE_CACHE
    if cache.exists() and not force_rebuild:
        print(f"Loading cached reference from {cache.name}")
        return pd.read_parquet(cache)

    if not FEATURES_PARQUET.exists():
        raise SystemExit(f"Missing {FEATURES_PARQUET}. Run Phase 1 first.")
    cutoff = int(CUTOFF_FILE.read_text().strip())
    print(f"Building reference sample (step <= {cutoff}, n={DRIFT_REFERENCE_SAMPLE_N})")
    df = pd.read_parquet(
        FEATURES_PARQUET,
        columns=FEATURE_COLS + ["step"],
        filters=[("step", "<=", cutoff)],
    )
    n = min(DRIFT_REFERENCE_SAMPLE_N, len(df))
    sample = df.sample(n, random_state=42)[FEATURE_COLS].astype("float32")
    sample = sample.reset_index(drop=True)

    cache.parent.mkdir(parents=True, exist_ok=True)
    sample.to_parquet(cache, index=False)
    print(f"  cached -> {cache.name}")
    return sample


def fetch_current(n: int) -> pd.DataFrame:
    """Pull recent feature rows from the live service."""
    print(f"Fetching {n} current feature rows from {SERVICE_URL}/sample_features ...")
    try:
        r = httpx.get(
            f"{SERVICE_URL}/sample_features",
            params={"n": n},
            timeout=30.0,
        )
    except httpx.RequestError as e:
        raise SystemExit(
            f"Cannot reach scoring service at {SERVICE_URL}: {e}\n"
            "Is the service running? Check: curl http://127.0.0.1:8000/health"
        )
    if r.status_code == 404:
        raise SystemExit(
            "Feature buffer is empty. Score some transactions first:\n"
            "  python scripts/kafka_producer.py --tps 100 --limit 2000"
        )
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data["features"])
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        raise SystemExit(f"Current features missing columns: {missing}")
    return df[FEATURE_COLS].astype("float32").reset_index(drop=True)


def simulate_drift(df: pd.DataFrame) -> pd.DataFrame:
    """Perturb ~20/31 columns to simulate a real distribution shift."""
    print("Simulating drift: perturbing 20 columns")
    df = df.copy()
    perturbations = {
        "amount":                   lambda x: x * 5.0,
        "hour_of_day":              lambda x: (x + 12) % 24,
        "amount_to_balance_ratio":  lambda x: x * 3.0,
        "oldbalanceOrg":            lambda x: x * 2.0,
        "orig_sum_1h":              lambda x: x * 2.0,
        "orig_sum_6h":              lambda x: x * 2.0,
        "orig_sum_24h":             lambda x: x * 2.0,
        "orig_prior_avg_amount":    lambda x: x * 2.0,
        "orig_prior_max_amount":    lambda x: x * 2.0,
        "orig_amount_vs_avg":       lambda x: x * 3.0,
        "orig_amount_vs_max":       lambda x: x * 3.0,
        "dest_prior_avg_amount":    lambda x: x * 2.0,
        "dest_prior_max_amount":    lambda x: x * 2.0,
        "dest_amount_vs_avg":       lambda x: x * 3.0,
        "dest_amount_vs_max":       lambda x: x * 3.0,
        "is_transfer":              lambda x: 1.0 - x,
        "is_cash_out":              lambda x: 1.0 - x,
        "is_payment":               lambda x: 1.0 - x,
        "is_cash_in":               lambda x: 1.0 - x,
        "is_debit":                 lambda x: 1.0 - x,
    }
    for col, fn in perturbations.items():
        if col in df.columns:
            df[col] = fn(df[col]).astype("float32")
    return df


def extract_summary(report_dict: dict) -> dict:
    """Extract drift share from Evidently's DatasetDriftMetric.

    IMPORTANT: Evidently 0.4/0.5/0.6 place BOTH a `drift_share` field
    (which is the CONFIG THRESHOLD, e.g. 0.5) and `share_of_drifted_columns`
    (the ACTUAL computed share) into the metric result. Reading `drift_share`
    directly returns the threshold, not the measurement — verified bug.
    We compute from the raw counts, which is unambiguous.
    """
    for m in report_dict.get("metrics", []):
        if m.get("metric") == "DatasetDriftMetric":
            r = m.get("result", {})
            n_drifted = int(r.get("number_of_drifted_columns", 0))
            n_total   = int(r.get("number_of_columns", 0))

            # Compute directly from counts — always correct.
            if n_total > 0:
                share = n_drifted / n_total
            else:
                # No columns tested: fall back to Evidently's own fields
                share = r.get("share_of_drifted_columns")
                if share is None:
                    share = 0.0

            return {
                "drift_share": float(share),
                "drifted_columns": n_drifted,
                "total_columns": n_total,
                "dataset_drift": bool(r.get("dataset_drift", False)),
            }
    return {"drift_share": 0.0, "drifted_columns": 0,
            "total_columns": 0, "dataset_drift": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-n", type=int, default=DRIFT_CURRENT_SAMPLE_N,
                    help="how many current rows to pull from the service")
    ap.add_argument("--simulate-drift", action="store_true",
                    help="perturb current features to force a drift report")
    ap.add_argument("--rebuild-reference", action="store_true",
                    help="ignore cached reference and rebuild from parquet")
    args = ap.parse_args()

    report_dir = PROJECT_ROOT / DRIFT_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    reference = build_reference_sample(force_rebuild=args.rebuild_reference)
    current   = fetch_current(args.current_n)

    if args.simulate_drift:
        current = simulate_drift(current)

    print(f"  reference: {len(reference):,} rows")
    print(f"  current:   {len(current):,} rows")
    print(f"  features:  {len(FEATURE_COLS)}")
    print("Running Evidently DataDriftPreset ...")

    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=reference, current_data=current)
    report_dict = report.as_dict()
    summary = extract_summary(report_dict)

    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    json_path = report_dir / f"drift_{ts}.json"
    html_path = report_dir / f"drift_{ts}.html"

    json_path.write_text(json.dumps(report_dict, indent=2, default=str),
                         encoding="utf-8")
    report.save_html(str(html_path))

    latest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "drift_share": summary["drift_share"],
        "drifted_columns": summary["drifted_columns"],
        "total_columns": summary["total_columns"],
        "dataset_drift": summary["dataset_drift"],
        "simulated_drift": bool(args.simulate_drift),
        "reference_rows": len(reference),
        "current_rows": len(current),
        "report_html_path": str(html_path.relative_to(PROJECT_ROOT)),
        "report_json_path": str(json_path.relative_to(PROJECT_ROOT)),
    }
    (PROJECT_ROOT / DRIFT_LATEST_JSON).write_text(
        json.dumps(latest, indent=2), encoding="utf-8"
    )

    print()
    print("=== Drift report ===")
    print(f"  drift_share       : {summary['drift_share']:.4f}")
    print(f"  drifted_columns   : {summary['drifted_columns']} / {summary['total_columns']}")
    print(f"  dataset_drift     : {summary['dataset_drift']}")
    print(f"  simulated         : {args.simulate_drift}")
    print(f"  json  -> {json_path.relative_to(PROJECT_ROOT)}")
    print(f"  html  -> {html_path.relative_to(PROJECT_ROOT)}")
    print(f"  latest -> {DRIFT_LATEST_JSON}")


if __name__ == "__main__":
    main()