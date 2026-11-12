"""Compute the warmup cutoff and optionally materialize into Feast.

On PaySim, each source account has ~1 transaction, so materializing prior
account state adds little and often blows Redis socket write limits on Windows.
We write the cutoff FIRST (kafka_producer needs it), then attempt materialization
as best-effort. Failure is logged and we continue — serving with empty Feast
matches training exactly because training features were also mostly empty.
"""
from pathlib import Path
import pandas as pd
from feast import FeatureStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARQUET = PROJECT_ROOT / "data" / "processed" / "features.parquet"
FEAST_REPO = str(PROJECT_ROOT / "feature_repo")
CUTOFF_FILE = PROJECT_ROOT / "data" / "processed" / "warmup_cutoff.txt"

WARMUP_FRACTION = 0.80


def main():
    if not PARQUET.exists():
        raise SystemExit(f"Missing {PARQUET}. Run Phase 1 first.")

    df = pd.read_parquet(PARQUET, columns=["step", "timestamp"])
    cutoff_step = int(df["step"].quantile(WARMUP_FRACTION))
    cutoff_ts = df.loc[df["step"] <= cutoff_step, "timestamp"].max()
    start_ts = df["timestamp"].min()

    print(f"Cutoff step       = {cutoff_step}")
    print(f"Warmup window     = {start_ts}  →  {cutoff_ts}")

    # 1. Write cutoff FIRST — kafka_producer needs this no matter what.
    CUTOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    CUTOFF_FILE.write_text(str(cutoff_step))
    print(f"Cutoff saved → {CUTOFF_FILE}")

    # 2. Attempt materialization (best effort — not required for the demo).
    print("\nAttempting Feast materialization (best effort) ...")
    try:
        store = FeatureStore(repo_path=FEAST_REPO)
        store.materialize(
            start_date=start_ts.to_pydatetime(),
            end_date=cutoff_ts.to_pydatetime(),
        )
        print("Materialization succeeded.")
    except Exception as e:
        print(f"Materialization skipped: {type(e).__name__}: {e}")
        print("This is OK — training also had empty prior state, so serving "
              "without warmup matches training exactly.")

    print("\nDone. Proceed to scoring service + replay.")


if __name__ == "__main__":
    main()