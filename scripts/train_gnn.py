"""Train a heterogeneous GNN for ring detection (v4: balanced-batch training).

Fix vs v3: instead of one loss over 1.24M nodes with pos_weight, do a full-
graph forward pass and compute loss only on a balanced sample of 40 pos + 400
neg nodes per epoch. This is standard for extreme-imbalance node classification.
"""
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch_geometric.nn import HeteroConv, GATConv, Linear
from sklearn.metrics import average_precision_score, roc_auc_score, precision_recall_curve
import mlflow

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GRAPH_FILE  = PROJECT_ROOT / "data" / "processed" / "graph_full.pt"
MODEL_OUT   = PROJECT_ROOT / "models" / "gnn_model.pt"
MLFLOW_DB   = PROJECT_ROOT / "mlflow.db"
MLFLOW_URI  = f"sqlite:///{MLFLOW_DB.as_posix()}"
EXPERIMENT  = "fraud-detection-gnn"

VAL_RINGS     = {"ring_07", "ring_08"}
VAL_NORMAL_N  = 10_000
NEG_PER_POS   = 10          # 40 pos × 10 = 400 negatives in each balanced batch
HIDDEN        = 16
HEADS         = 2
LAYERS        = 2
EPOCHS        = 30
PATIENCE      = 10
LR            = 5e-3
SEED          = 42
CLIP          = 5.0

ACCOUNT_IN_DIM = 3
DEVICE_IN_DIM  = 1
CARD_IN_DIM    = 1


class RingGNN(torch.nn.Module):
    def __init__(self, hidden=HIDDEN, heads=HEADS, layers=LAYERS):
        super().__init__()
        dim = hidden * heads
        self.proj = torch.nn.ModuleDict({
            "account": Linear(ACCOUNT_IN_DIM, dim),
            "device":  Linear(DEVICE_IN_DIM,  dim),
            "card":    Linear(CARD_IN_DIM,    dim),
        })
        self.convs = torch.nn.ModuleList()
        for _ in range(layers):
            self.convs.append(HeteroConv({
                ("account", "uses_device", "device"): GATConv(dim, hidden, heads=heads, concat=True, add_self_loops=False),
                ("device",  "used_by_account", "account"): GATConv(dim, hidden, heads=heads, concat=True, add_self_loops=False),
                ("account", "uses_card", "card"):       GATConv(dim, hidden, heads=heads, concat=True, add_self_loops=False),
                ("card",    "used_by_account", "account"): GATConv(dim, hidden, heads=heads, concat=True, add_self_loops=False),
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


def build_masks(ring_ids, y):
    ring_ids_arr = np.array(ring_ids, dtype=object)
    is_val_ring = np.isin(ring_ids_arr, list(VAL_RINGS))
    is_normal = (y == 0)
    rng = np.random.default_rng(SEED)
    normal_idx = np.where(is_normal)[0]
    val_normal = rng.choice(normal_idx, size=min(VAL_NORMAL_N, len(normal_idx)), replace=False)
    val_normal_mask = np.zeros(len(y), dtype=bool)
    val_normal_mask[val_normal] = True
    val_mask = is_val_ring | val_normal_mask
    train_mask = ~val_mask
    return torch.tensor(train_mask, dtype=torch.bool), torch.tensor(val_mask, dtype=torch.bool)


def main():
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    print(f"Loading {GRAPH_FILE}")
    payload = torch.load(GRAPH_FILE, weights_only=False)
    data = payload["data"]
    ring_ids = payload["ring_ids"]
    y = data["account"].y
    print(f"  accounts: {data['account'].num_nodes:,}  y_pos: {int(y.sum())}")
    print(f"  account.x: {tuple(data['account'].x.shape)}")

    train_mask, val_mask = build_masks(ring_ids, y.numpy())
    train_pos_idx = torch.where(train_mask & (y == 1))[0]
    train_neg_idx = torch.where(train_mask & (y == 0))[0]
    n_pos_train = int(len(train_pos_idx))
    n_neg_train = int(len(train_neg_idx))
    n_pos_val   = int((y[val_mask] == 1).sum())
    n_neg_val   = int((y[val_mask] == 0).sum())
    print(f"  train: {int(train_mask.sum()):,} (pos={n_pos_train}, neg={n_neg_train})")
    print(f"  val  : {int(val_mask.sum()):,}   (pos={n_pos_val}, neg={n_neg_val})")
    print(f"  balanced batch size: {n_pos_train} pos + {n_pos_train * NEG_PER_POS} neg = {n_pos_train * (1 + NEG_PER_POS)}")

    model = RingGNN()
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=5e-4)

    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(EXPERIMENT)

    best_val_ap = -1.0
    best_state = None
    epochs_no_improve = 0

    with mlflow.start_run(run_name="gnn_ring_detector_v4_balanced_batch"):
        mlflow.log_params({
            "hidden": HIDDEN, "heads": HEADS, "layers": LAYERS,
            "epochs": EPOCHS, "patience": PATIENCE, "lr": LR,
            "loss": "BCE (balanced batch)",
            "neg_per_pos": NEG_PER_POS,
            "account_in_dim": ACCOUNT_IN_DIM,
            "residual": True, "skip": True, "clip": CLIP,
            "val_rings": ",".join(sorted(VAL_RINGS)),
            "n_accounts": data["account"].num_nodes,
            "n_pos_train": n_pos_train,
        })

        # Pre-training snapshot
        model.eval()
        with torch.no_grad():
            p0 = torch.sigmoid(model(data.x_dict, data.edge_index_dict)).numpy()
        print(f"  [init] ring_mean={p0[y.numpy()==1].mean():.4f}  "
              f"normal_mean={p0[y.numpy()==0].mean():.4f}")

        for epoch in range(1, EPOCHS + 1):
            model.train()
            opt.zero_grad()
            logits = model(data.x_dict, data.edge_index_dict)

            # Balanced batch loss: all pos + sampled neg
            n_neg = min(len(train_neg_idx), len(train_pos_idx) * NEG_PER_POS)
            perm = torch.randperm(len(train_neg_idx))[:n_neg]
            batch_idx = torch.cat([train_pos_idx, train_neg_idx[perm]])

            loss = F.binary_cross_entropy_with_logits(
                logits[batch_idx], y[batch_idx]
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
            opt.step()

            model.eval()
            with torch.no_grad():
                proba = torch.sigmoid(model(data.x_dict, data.edge_index_dict)).numpy()
            y_val = y[val_mask].numpy()
            p_val = proba[val_mask.numpy()]
            val_ap  = average_precision_score(y_val, p_val)
            val_auc = roc_auc_score(y_val, p_val) if len(set(y_val)) > 1 else 0.0

            y_np = y.numpy()
            ring_train_mean = proba[y_np == 1].mean()
            norm_train_mean = proba[y_np == 0].mean()

            mlflow.log_metrics(
                {"train_loss": loss.item(), "val_pr_auc": val_ap, "val_roc_auc": val_auc,
                 "ring_mean": float(ring_train_mean), "normal_mean": float(norm_train_mean)},
                step=epoch,
            )
            print(f"  epoch {epoch:02d}  loss={loss.item():.4f}  "
                  f"val_pr_auc={val_ap:.4f}  val_roc_auc={val_auc:.4f}  "
                  f"ring={ring_train_mean:.4f}  norm={norm_train_mean:.4f}")

            if val_ap > best_val_ap:
                best_val_ap = val_ap
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
                epochs_no_improve = 0
            else:
                epochs_no_improve += 1
                if epochs_no_improve >= PATIENCE:
                    print(f"  early stopping (no improvement for {PATIENCE} epochs)")
                    break

        model.load_state_dict(best_state)
        model.eval()
        with torch.no_grad():
            proba = torch.sigmoid(model(data.x_dict, data.edge_index_dict)).numpy()
        y_val = y[val_mask].numpy()
        p_val = proba[val_mask.numpy()]

        prec, rec, thresh = precision_recall_curve(y_val, p_val)
        f1s = 2 * prec * rec / (prec + rec + 1e-12)
        best_i = int(np.nanargmax(f1s))
        best_thr = float(thresh[best_i]) if best_i < len(thresh) else 0.5

        mlflow.log_metrics({
            "val_pr_auc_final": best_val_ap,
            "val_best_threshold": best_thr,
            "val_precision_at_best": float(prec[best_i]),
            "val_recall_at_best":    float(rec[best_i]),
            "val_f1_at_best":        float(f1s[best_i]),
        })

        MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "state_dict": model.state_dict(),
            "best_val_pr_auc": float(best_val_ap),
            "best_threshold":  best_thr,
            "account_in_dim":  ACCOUNT_IN_DIM,
        }, MODEL_OUT)
        mlflow.log_artifact(str(MODEL_OUT))

        print(f"\n=== GNN training complete ===")
        print(f"  best val PR-AUC : {best_val_ap:.4f}")
        print(f"  best threshold  : {best_thr:.4f}")
        print(f"  saved           : {MODEL_OUT}")


if __name__ == "__main__":
    main()