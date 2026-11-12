"""Forward pass on full graph → write per-account GNN scores to Redis."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import redis
import torch.nn.functional as F
from torch_geometric.nn import HeteroConv, GATConv, Linear

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from common.schema import (  # noqa: E402
    GNM_SCORE_PREFIX, GNM_RING_ID_PREFIX,
    GNM_DEVICE_PREFIX, GNM_CARD_PREFIX, GNM_RING_MEMBERS_PREFIX,
    REDIS_HOST, REDIS_PORT,
)

GRAPH_FILE = PROJECT_ROOT / "data" / "processed" / "graph_full.pt"
MODEL_FILE = PROJECT_ROOT / "models" / "gnn_model.pt"

HIDDEN, HEADS, LAYERS = 16, 2, 2
ACCOUNT_IN_DIM = 3
DEVICE_IN_DIM  = 1
CARD_IN_DIM    = 1


class RingGNN(torch.nn.Module):
    def __init__(self):
        super().__init__()
        dim = HIDDEN * HEADS
        self.proj = torch.nn.ModuleDict({
            "account": Linear(ACCOUNT_IN_DIM, dim),
            "device":  Linear(DEVICE_IN_DIM,  dim),
            "card":    Linear(CARD_IN_DIM,    dim),
        })
        self.convs = torch.nn.ModuleList()
        for _ in range(LAYERS):
            self.convs.append(HeteroConv({
                ("account", "uses_device", "device"): GATConv(dim, HIDDEN, heads=HEADS, concat=True, add_self_loops=False),
                ("device",  "used_by_account", "account"): GATConv(dim, HIDDEN, heads=HEADS, concat=True, add_self_loops=False),
                ("account", "uses_card", "card"):       GATConv(dim, HIDDEN, heads=HEADS, concat=True, add_self_loops=False),
                ("card",    "used_by_account", "account"): GATConv(dim, HIDDEN, heads=HEADS, concat=True, add_self_loops=False),
            }, aggr="sum"))
        self.out  = Linear(dim, 1)
        self.skip = Linear(ACCOUNT_IN_DIM, 1)

    def forward(self, x_dict, edge_index_dict):
        x_acc_raw = x_dict["account"]
        h = {k: F.relu(self.proj[k](x_dict[k])) for k in x_dict}
        for conv in self.convs:
            h_new = conv(h, edge_index_dict)
            h = {k: F.relu(h[k] + h_new[k]) for k in h if k in h_new}
        return self.out(h["account"]).squeeze(-1) + self.skip(x_acc_raw).squeeze(-1)


def connect_redis(max_retries=3, delay=2.0):
    for attempt in range(1, max_retries + 1):
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                            decode_responses=True, socket_connect_timeout=3)
            r.ping()
            return r
        except redis.exceptions.ConnectionError as e:
            if attempt < max_retries:
                print(f"  attempt {attempt}/{max_retries} failed. retrying in {delay}s ...")
                time.sleep(delay)
            else:
                raise SystemExit(
                    f"\nCannot reach Redis at {REDIS_HOST}:{REDIS_PORT}.\n"
                    "Fix: docker compose up -d && docker exec fraud-redis redis-cli ping"
                )


def main():
    print(f"Loading graph {GRAPH_FILE}")
    payload = torch.load(GRAPH_FILE, weights_only=False)
    data = payload["data"]
    account_ids = payload["account_ids"]
    ring_ids    = payload["ring_ids"]
    print(f"  accounts: {len(account_ids):,}")
    print(f"  account.x: {tuple(data['account'].x.shape)}")

    print(f"Loading model {MODEL_FILE}")
    ckpt = torch.load(MODEL_FILE, weights_only=False)
    if ckpt.get("account_in_dim") != ACCOUNT_IN_DIM:
        raise SystemExit(f"Model in_dim={ckpt.get('account_in_dim')} != {ACCOUNT_IN_DIM}. Re-run train_gnn.py.")
    model = RingGNN()
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    print(f"  best val PR-AUC: {ckpt['best_val_pr_auc']:.4f}")

    print("Forward pass ...")
    with torch.no_grad():
        proba = torch.sigmoid(model(data.x_dict, data.edge_index_dict)).numpy()
    print(f"  done, {len(proba):,} account scores")
    print(f"  score range: [{proba.min():.4f}, {proba.max():.4f}]  mean={proba.mean():.4f}")

    y_true = data["account"].y.numpy()
    if (y_true == 1).any():
        ring_scores = proba[y_true == 1]
        norm_scores = proba[y_true == 0]
        print(f"  ring   scores: mean={ring_scores.mean():.4f}  min={ring_scores.min():.4f}  max={ring_scores.max():.4f}")
        print(f"  normal scores: mean={norm_scores.mean():.4f}  min={norm_scores.min():.4f}  max={norm_scores.max():.4f}")

    print(f"Connecting to Redis {REDIS_HOST}:{REDIS_PORT} ...")
    r = connect_redis()
    print("  connected")

    print("Clearing previous gnn:* keys ...")
    old_keys = 0
    for prefix in (GNM_SCORE_PREFIX, GNM_RING_ID_PREFIX,
                   GNM_DEVICE_PREFIX, GNM_CARD_PREFIX, GNM_RING_MEMBERS_PREFIX):
        cursor = 0
        while True:
            cursor, batch = r.scan(cursor=cursor, match=f"{prefix}*", count=10_000)
            if batch:
                r.delete(*batch)
                old_keys += len(batch)
            if cursor == 0:
                break
    print(f"  removed {old_keys} old keys")

    print("Writing scores ...")
    pipe = r.pipeline()
    buf = 0
    for i, (acc, p) in enumerate(zip(account_ids, proba)):
        pipe.set(f"{GNM_SCORE_PREFIX}{acc}", f"{float(p):.6f}")
        buf += 1
        if buf >= 10_000:
            pipe.execute()
            pipe = r.pipeline()
            buf = 0
        if (i + 1) % 200_000 == 0:
            print(f"  {i+1:,}/{len(account_ids):,}")
    if buf:
        pipe.execute()

    print("Writing ring metadata ...")
    ring_members: dict[str, list[str]] = {}
    for acc, rid in zip(account_ids, ring_ids):
        if rid:
            ring_members.setdefault(rid, []).append(acc)

    for acc, rid in zip(account_ids, ring_ids):
        if not rid:
            continue
        idx = int(rid.split("_")[1])
        r.set(f"{GNM_RING_ID_PREFIX}{acc}", rid)
        r.set(f"{GNM_DEVICE_PREFIX}{acc}", f"dev_ring_{idx:02d}")
        r.set(f"{GNM_CARD_PREFIX}{acc}",   f"card_ring_{idx:02d}")

    for rid, members in ring_members.items():
        r.set(f"{GNM_RING_MEMBERS_PREFIX}{rid}", json.dumps(members))

    print(f"\n=== Done ===")
    print(f"  scores   : {len(account_ids):,}")
    print(f"  rings    : {len(ring_members)} rings, {sum(len(v) for v in ring_members.values())} members")


if __name__ == "__main__":
    main()