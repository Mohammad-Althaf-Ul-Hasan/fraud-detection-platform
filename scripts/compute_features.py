"""Feature engineering for PaySim.

Rules:
  * Velocity / deviation features are computed from PRIOR transactions only.
    For a txn at time T, feature = state at T (before this txn).
  * Feast serves these at inference → identical semantics, no leakage.
  * Per-transaction fields (amount, balances, balance errors) are also
    computed here so training data is complete; at serving they travel in
    the request payload.
"""
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IN_PARQUET = PROJECT_ROOT / "data" / "processed" / "transactions.parquet"
OUT_PARQUET = PROJECT_ROOT / "data" / "processed" / "features.parquet"

WINDOWS_HOURS = [1, 6, 24]


# ---------------------------------------------------------------------------
# 1. Velocity features (counts and sums of prior txns, rolling window)
# ---------------------------------------------------------------------------
def _velocity_for_entity(df: pd.DataFrame, entity_col: str,
                         prefix: str) -> pd.DataFrame:
    """For each row, count / sum of *prior* txns of the same entity
    within the last W hours. Current txn is excluded (right index = i)."""
    df = df.sort_values([entity_col, "step"]).reset_index(drop=True)

    n = len(df)
    outputs = {}
    for w in WINDOWS_HOURS:
        outputs[f"{prefix}_count_{w}h"] = np.zeros(n, dtype=np.int32)
        outputs[f"{prefix}_sum_{w}h"] = np.zeros(n, dtype=np.float64)

    groups = df.groupby(entity_col, sort=False).indices
    steps_all = df["step"].to_numpy()
    amounts_all = df["amount"].to_numpy()

    for idx in groups.values():
        steps = steps_all[idx]
        amounts = amounts_all[idx]
        cumsum = np.concatenate([[0.0], np.cumsum(amounts)])
        right = np.arange(len(steps))            # excludes current (strict <)

        for w in WINDOWS_HOURS:
            left = np.searchsorted(steps, steps - w, side="left")
            outputs[f"{prefix}_count_{w}h"][idx] = right - left
            outputs[f"{prefix}_sum_{w}h"][idx] = cumsum[right] - cumsum[left]

    for name, arr in outputs.items():
        df[name] = arr

    return df


# ---------------------------------------------------------------------------
# 2. Amount deviation (current amount vs entity's prior average / max)
# ---------------------------------------------------------------------------
def _amount_deviation(df: pd.DataFrame, entity_col: str, prefix: str) -> pd.DataFrame:
    df = df.sort_values([entity_col, "step"]).reset_index(drop=True)

    # prior sum and prior count
    grp = df.groupby(entity_col, sort=False)
    prior_sum = grp["amount"].cumsum() - df["amount"]
    prior_cnt = grp.cumcount().clip(lower=1)
    prior_avg = (prior_sum / prior_cnt).fillna(0.0)
    prior_max = grp["amount"].transform(lambda s: s.shift().cummax()).fillna(0.0)

    df[f"{prefix}_prior_avg_amount"] = prior_avg
    df[f"{prefix}_prior_max_amount"] = prior_max
    df[f"{prefix}_amount_vs_avg"] = df["amount"] / (prior_avg + 1.0)
    df[f"{prefix}_amount_vs_max"] = df["amount"] / (prior_max + 1.0)

    return df


# ---------------------------------------------------------------------------
# 3. Per-transaction features
# ---------------------------------------------------------------------------
def add_transaction_features(df: pd.DataFrame) -> pd.DataFrame:
    df["hour_of_day"] = (df["step"] % 24).astype(np.int16)

    # Type one-hot
    for t in ["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"]:
        df[f"is_{t.lower()}"] = (df["type"] == t).astype(np.int8)

    # Balance consistency (PaySim: ~0 for real txns)
    df["balance_error_orig"] = (df["oldbalanceOrg"] - df["amount"]
                                - df["newbalanceOrig"]).astype(np.float32)
    df["balance_error_dest"] = (df["oldbalanceDest"] + df["amount"]
                                - df["newbalanceDest"]).astype(np.float32)
    df["amount_to_balance_ratio"] = (df["amount"] / (df["oldbalanceOrg"] + 1.0)).astype(np.float32)

    # Destination is a merchant (M-prefix in PaySim)
    df["dest_is_merchant"] = df["nameDest"].str.startswith("M").astype(np.int8)

    return df


# ---------------------------------------------------------------------------
# 4. Build the final feature table
# ---------------------------------------------------------------------------
def build_feature_table(df: pd.DataFrame) -> pd.DataFrame:
    print("Computing orig velocity features …")
    df = _velocity_for_entity(df, "nameOrig", "orig")

    print("Computing dest velocity features …")
    df = _velocity_for_entity(df, "nameDest", "dest")

    print("Computing orig amount deviation …")
    df = _amount_deviation(df, "nameOrig", "orig")

    print("Computing dest amount deviation …")
    df = _amount_deviation(df, "nameDest", "dest")

    print("Adding transaction-level features …")
    df = add_transaction_features(df)

    # Cast integers down for memory
    for c in df.columns:
        if df[c].dtype == np.int64:
            df[c] = df[c].astype(np.int32)
        elif df[c].dtype == np.float64 and c not in {"amount", "oldbalanceOrg",
                                                     "newbalanceOrig",
                                                     "oldbalanceDest",
                                                     "newbalanceDest"}:
            df[c] = df[c].astype(np.float32)

    return df


def main():
    print(f"Loading {IN_PARQUET} …")
    df = pd.read_parquet(IN_PARQUET)
    print(f"  {len(df):,} rows")

    features = build_feature_table(df)

    print(f"\nFeature columns: {len(features.columns)}")
    print(f"Saving → {OUT_PARQUET}")
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUT_PARQUET, index=False)
    print("Done.")


if __name__ == "__main__":
    main()