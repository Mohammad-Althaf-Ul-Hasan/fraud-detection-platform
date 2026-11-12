"""Load PaySim, validate schema, and save a parquet version with timestamps."""
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_ROOT / "data" / "raw" / "paysim.csv"
PROCESSED_PARQUET = PROJECT_ROOT / "data" / "processed" / "transactions.parquet"

REQUIRED_COLS = {
    "step", "type", "amount", "nameOrig",
    "oldbalanceOrg", "newbalanceOrig",
    "nameDest", "oldbalanceDest", "newbalanceDest",
    "isFraud", "isFlaggedFraud",
}


def load_raw() -> pd.DataFrame:
    if not RAW_CSV.exists():
        raise FileNotFoundError(
            f"PaySim CSV not found at {RAW_CSV}\n"
            "Download from https://www.kaggle.com/datasets/ealaxi/paysim1 "
            "and place the CSV at data/raw/paysim.csv"
        )

    df = pd.read_csv(RAW_CSV)
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    # step is hours since simulation start → convert to real timestamp
    base = pd.Timestamp("2024-01-01")
    df["timestamp"] = base + pd.to_timedelta(df["step"], unit="h")

    return df


def main():
    df = load_raw()
    fraud = int(df["isFraud"].sum())
    rate = df["isFraud"].mean() * 100

    print(f"Rows:            {len(df):,}")
    print(f"Unique nameOrig: {df['nameOrig'].nunique():,}")
    print(f"Unique nameDest: {df['nameDest'].nunique():,}")
    print(f"Fraud txns:      {fraud:,} ({rate:.4f}%)")
    print(f"Time span:       {df['step'].min()}h → {df['step'].max()}h "
          f"({df['step'].max()/24:.1f} days)")

    if rate > 5.0:
        print("WARNING: fraud rate unusually high — is this the correct file?")

    PROCESSED_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PROCESSED_PARQUET, index=False)
    print(f"Saved → {PROCESSED_PARQUET}")


if __name__ == "__main__":
    main()