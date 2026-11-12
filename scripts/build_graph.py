"""Build a heterogeneous graph from features_with_rings.parquet.

Account features (3):  log1p(amount), shared_device_degree, shared_card_degree
  The first is log-scaled so it doesn't drown out the structural features.
  The last two are the actual ring signal (1 for normal, 4-8 for ring).

Device/card features (1): degree.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch_geometric.data import HeteroData

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IN_PARQUET = PROJECT_ROOT / "data" / "processed" / "features_with_rings.parquet"
OUT_FILE   = PROJECT_ROOT / "data" / "processed" / "graph_full.pt"
CUTOFF_FILE = PROJECT_ROOT / "data" / "processed" / "warmup_cutoff.txt"


def main():
    cutoff = int(CUTOFF_FILE.read_text().strip())
    print(f"Cutoff step = {cutoff}")

    cols = ["step", "nameOrig", "device_id", "card_id",
            "is_ring_member", "ring_id", "amount"]
    print(f"Loading {IN_PARQUET} ...")
    df = pd.read_parquet(IN_PARQUET, columns=cols)
    live = df[df["step"] > cutoff].copy().reset_index(drop=True)
    del df
    print(f"  live rows: {len(live):,}")

    account_ids = live["nameOrig"].unique()
    n_acc = len(account_ids)
    acc_to_idx = {a: i for i, a in enumerate(account_ids)}
    print(f"  accounts: {n_acc:,}")

    device_ids  = live["device_id"].unique()
    card_ids    = live["card_id"].unique()
    dev_to_idx  = {d: i for i, d in enumerate(device_ids)}
    card_to_idx = {c: i for i, c in enumerate(card_ids)}
    print(f"  devices:  {len(device_ids):,}")
    print(f"  cards:    {len(card_ids):,}")

    # Last txn per account → base info
    last = live.sort_values("step").drop_duplicates("nameOrig", keep="last")
    last = last.set_index("nameOrig").loc[account_ids]
    y_account = last["is_ring_member"].values.astype(np.float32)
    ring_ids_per_account = last["ring_id"].fillna("").astype(str).values
    print(f"  positives (ring members): {int(y_account.sum())}")

    acc_idx_arr  = live["nameOrig"].map(acc_to_idx).to_numpy()
    dev_idx_arr  = live["device_id"].map(dev_to_idx).to_numpy()
    card_idx_arr = live["card_id"].map(card_to_idx).to_numpy()

    pairs_dev  = np.unique(np.stack([acc_idx_arr, dev_idx_arr],  axis=1), axis=0)
    pairs_card = np.unique(np.stack([acc_idx_arr, card_idx_arr], axis=1), axis=0)

    dev_degree  = np.bincount(pairs_dev[:, 1],  minlength=len(device_ids)).astype(np.float32)
    card_degree = np.bincount(pairs_card[:, 1], minlength=len(card_ids)).astype(np.float32)

    acc_shared_dev_deg  = np.zeros(n_acc, dtype=np.float32)
    acc_shared_card_deg = np.zeros(n_acc, dtype=np.float32)
    acc_shared_dev_deg[pairs_dev[:, 0]]   = dev_degree[pairs_dev[:, 1]]
    acc_shared_card_deg[pairs_card[:, 0]] = card_degree[pairs_card[:, 1]]

    log_amount = np.log1p(last["amount"].values).astype(np.float32)

    account_x = np.stack([
        log_amount,
        acc_shared_dev_deg,
        acc_shared_card_deg,
    ], axis=1).astype(np.float32)          # (n_acc, 3)

    data = HeteroData()
    data["account"].x = torch.tensor(account_x, dtype=torch.float32)
    data["account"].y = torch.tensor(y_account, dtype=torch.float32)
    data["device"].x  = torch.tensor(dev_degree.reshape(-1, 1),  dtype=torch.float32)
    data["card"].x    = torch.tensor(card_degree.reshape(-1, 1), dtype=torch.float32)

    data["account", "uses_device", "device"].edge_index = torch.tensor(pairs_dev.T,  dtype=torch.long)
    data["device",  "used_by_account", "account"].edge_index = torch.tensor(pairs_dev.T[::-1].copy(),  dtype=torch.long)
    data["account", "uses_card", "card"].edge_index     = torch.tensor(pairs_card.T, dtype=torch.long)
    data["card",    "used_by_account", "account"].edge_index = torch.tensor(pairs_card.T[::-1].copy(), dtype=torch.long)

    payload = {
        "data": data,
        "account_ids": account_ids.tolist(),
        "ring_ids": ring_ids_per_account.tolist(),
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, OUT_FILE)
    size_mb = OUT_FILE.stat().st_size / 1e6
    print(f"\nSaved → {OUT_FILE}  ({size_mb:.1f} MB)")
    print(f"  account.x: {tuple(data['account'].x.shape)}   (log_amount + shared_dev + shared_card)")

    ring_mask = y_account == 1
    if ring_mask.any():
        print(f"  ring   shared_dev_deg: min={acc_shared_dev_deg[ring_mask].min():.0f} "
              f"max={acc_shared_dev_deg[ring_mask].max():.0f} "
              f"mean={acc_shared_dev_deg[ring_mask].mean():.2f}")
    print(f"  normal shared_dev_deg: min={acc_shared_dev_deg[~ring_mask].min():.0f} "
          f"max={acc_shared_dev_deg[~ring_mask].max():.0f}")


if __name__ == "__main__":
    main()