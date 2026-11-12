"""Inject synthetic fraud rings into the live window of PaySim.

Live window = step > warmup_cutoff (last ~20% of data).
Training rows are untouched.

Output: data/processed/features_with_rings.parquet
  + device_id       (default = unique per account; overridden for ring members)
  + card_id         (same pattern)
  + is_ring_member  (0/1)
  + ring_id         ("" for non-ring accounts)
"""
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IN_PARQUET   = PROJECT_ROOT / "data" / "processed" / "features.parquet"
OUT_PARQUET  = PROJECT_ROOT / "data" / "processed" / "features_with_rings.parquet"
CUTOFF_FILE  = PROJECT_ROOT / "data" / "processed" / "warmup_cutoff.txt"

N_RINGS       = 8
RING_SIZE_MIN = 4
RING_SIZE_MAX = 8
RANDOM_SEED   = 42


def _hash12(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:12]


def main():
    if not CUTOFF_FILE.exists():
        raise SystemExit(f"Missing {CUTOFF_FILE}. Run Phase 2 first.")
    cutoff = int(CUTOFF_FILE.read_text().strip())
    print(f"Warmup cutoff = step {cutoff}")

    print(f"\nLoading {IN_PARQUET} ...")
    df = pd.read_parquet(IN_PARQUET)
    print(f"  {len(df):,} rows, {len(df.columns)} cols")

    live_mask = df["step"] > cutoff
    n_live = int(live_mask.sum())
    print(f"Live window : {n_live:,} rows")

    # --- Default device/card: one per account (overridden for ring members) ---
    print("\nAssigning default device/card per account (live window only) ...")
    unique_accounts = df.loc[live_mask, "nameOrig"].unique()
    print(f"  {len(unique_accounts):,} unique accounts")

    dev_map  = {a: f"dev_{_hash12(a)}"  for a in unique_accounts}
    card_map = {a: f"card_{_hash12(a)}" for a in unique_accounts}

    # Training rows get empty strings (they don't join the graph)
    df["device_id"]      = ""
    df["card_id"]        = ""
    df["is_ring_member"] = np.int8(0)
    df["ring_id"]        = ""

    df.loc[live_mask, "device_id"] = df.loc[live_mask, "nameOrig"].map(dev_map)
    df.loc[live_mask, "card_id"]   = df.loc[live_mask, "nameOrig"].map(card_map)

    # --- Pick ring members (no overlap between rings) ---
    print(f"\nSelecting {N_RINGS} rings (size {RING_SIZE_MIN}-{RING_SIZE_MAX}) ...")
    rng = np.random.default_rng(RANDOM_SEED)
    shuffled = rng.permutation(unique_accounts)

    ring_assignments = {}       # account -> (ring_id, device_id, card_id)
    cursor = 0
    ring_summary = []

    for r in range(N_RINGS):
        size = int(rng.integers(RING_SIZE_MIN, RING_SIZE_MAX + 1))
        if cursor + size > len(shuffled):
            print(f"  WARN: not enough accounts for ring {r+1:02d}; stopping")
            break
        members = shuffled[cursor:cursor + size]
        cursor += size
        ring_id      = f"ring_{r+1:02d}"
        shared_dev   = f"dev_ring_{r+1:02d}"
        shared_card  = f"card_ring_{r+1:02d}"
        for acc in members:
            ring_assignments[acc] = (ring_id, shared_dev, shared_card)
        ring_summary.append((ring_id, size, shared_dev, shared_card))
        print(f"  {ring_id}: {size} accounts  dev={shared_dev}  card={shared_card}")

    # --- Apply ring assignments ---
    ring_id_map = {a: v[0] for a, v in ring_assignments.items()}
    dev_map_r   = {a: v[1] for a, v in ring_assignments.items()}
    card_map_r  = {a: v[2] for a, v in ring_assignments.items()}

    ring_rows_mask = live_mask & df["nameOrig"].isin(ring_assignments.keys())
    n_ring_rows = int(ring_rows_mask.sum())
    print(f"\nApplying to {n_ring_rows:,} rows across {len(ring_assignments)} accounts")

    df.loc[ring_rows_mask, "is_ring_member"] = 1
    df.loc[ring_rows_mask, "ring_id"]        = df.loc[ring_rows_mask, "nameOrig"].map(ring_id_map)
    df.loc[ring_rows_mask, "device_id"]      = df.loc[ring_rows_mask, "nameOrig"].map(dev_map_r)
    df.loc[ring_rows_mask, "card_id"]        = df.loc[ring_rows_mask, "nameOrig"].map(card_map_r)

    # --- Assertions ---
    print("\n=== Sanity checks ===")
    assert df.loc[~live_mask, "is_ring_member"].sum() == 0, \
        "training rows must have no rings"
    assert df.loc[live_mask, "is_ring_member"].sum() == n_ring_rows
    assert df.loc[live_mask, "device_id"].notna().all()
    assert (df.loc[live_mask, "device_id"] != "").all()

    for ring_id, size, _, _ in ring_summary:
        r = df["ring_id"] == ring_id
        accs = df.loc[r, "nameOrig"].unique()
        assert len(accs) == size, \
            f"{ring_id}: expected {size} accounts, got {len(accs)}"
        assert df.loc[r, "device_id"].nunique() == 1, f"{ring_id}: device leak"
        assert df.loc[r, "card_id"].nunique()   == 1, f"{ring_id}: card leak"
    print(f"  All {len(ring_summary)} rings OK")

    # No account in two rings
    seen = {}
    for a, (rid, _, _) in ring_assignments.items():
        assert a not in seen, f"account {a} in {seen[a]} and {rid}"
        seen[a] = rid
    print(f"  No overlapping accounts")

    print(f"\nSaving → {OUT_PARQUET}")
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    size_mb = OUT_PARQUET.stat().st_size / 1e6
    print(f"  {size_mb:.1f} MB")
    print(f"  Columns: {len(df.columns)} (added 4)")


if __name__ == "__main__":
    main()