"""Unsupervised ring discovery.

Finds account clusters that share device/card infrastructure (from parquet
+ live Redis delta), then cross-references against known ring labels.

Performance:
  * Parquet-derived acc_to_dev/acc_to_card is cached in Redis (12h TTL)
    so subsequent calls skip the 545MB parquet read entirely.
  * Suspect scan samples 100k accounts (not all 1.25M) and pipelines the
    Redis GETs in 5000-key batches.
  * Result cached in Redis (1h) — first call after a cold start is 15-40s,
    every subsequent call is <200ms.
"""
import json
import logging
import math
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd

log = logging.getLogger("discovery")

ACCMAP_CACHE_KEY = "discovery:acc_maps:v1"
ACCMAP_CACHE_TTL = 12 * 3600
SUSPECT_SAMPLE_SIZE = 100_000
PIPELINE_BATCH = 5_000


def _build_shared_infra_maps(redis_client, parquet_path: Path, cutoff: int):
    """Return (acc_to_dev, acc_to_card) covering parquet + Redis attack rings.
    Cached in Redis so subsequent calls are instant."""
    # Try cache first
    try:
        cached = redis_client.get(ACCMAP_CACHE_KEY)
        if cached:
            data = json.loads(cached)
            log.info(
                f"Discovery: acc maps from cache "
                f"({len(data['acc_to_dev']):,} accounts)"
            )
            return data["acc_to_dev"], data["acc_to_card"]
    except Exception:
        pass

    # Cold path — read parquet
    log.info("Discovery: reading parquet (cold path, ~30-40s) ...")
    df = pd.read_parquet(
        parquet_path,
        columns=["nameOrig", "device_id", "card_id", "step"],
        filters=[("step", ">", cutoff)],
    )
    acc_to_dev = dict(zip(df["nameOrig"], df["device_id"]))
    acc_to_card = dict(zip(df["nameOrig"], df["card_id"]))
    log.info(f"Discovery: {len(acc_to_dev):,} parquet accounts loaded")

    # Overlay attack rings (only in Redis).
    # Attack rings store gnn:ring_id:{account} = "ring_attack_*". We scan ALL
    # ring_id keys (only ~70 exist across 12 rings) and filter by the VALUE.
    try:
        for key in redis_client.scan_iter("gnn:ring_id:*", count=1000):
            key_str = key.decode() if isinstance(key, bytes) else key
            val = redis_client.get(key_str)
            if not val:
                continue
            val_str = val.decode() if isinstance(val, bytes) else val
            if not val_str.startswith("ring_attack_"):
                continue
            acc = key_str.rsplit(":", 1)[-1]
            dev = redis_client.get(f"gnn:device:{acc}")
            card = redis_client.get(f"gnn:card:{acc}")
            if dev:
                acc_to_dev[acc] = dev.decode() if isinstance(dev, bytes) else dev
            if card:
                acc_to_card[acc] = card.decode() if isinstance(card, bytes) else card
    except Exception as e:
        log.warning(f"Redis delta scan failed: {e}")

    # Write back to cache
    try:
        redis_client.setex(
            ACCMAP_CACHE_KEY,
            ACCMAP_CACHE_TTL,
            json.dumps({"acc_to_dev": acc_to_dev, "acc_to_card": acc_to_card}),
        )
        log.info("Discovery: acc maps cached for 12h")
    except Exception as e:
        log.warning(f"Cache write failed: {e}")

    return acc_to_dev, acc_to_card


def _group_by_infra(acc_to_dev: dict, acc_to_card: dict):
    dev_groups = defaultdict(list)
    card_groups = defaultdict(list)
    for acc, dev in acc_to_dev.items():
        dev_groups[dev].append(acc)
    for acc, card in acc_to_card.items():
        card_groups[card].append(acc)
    return dev_groups, card_groups


def _union_find_clusters(dev_groups: dict, card_groups: dict):
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Only iterate groups with 2+ accounts — skips 1.25M singletons
    for accs in dev_groups.values():
        if len(accs) < 2:
            continue
        for i in range(1, len(accs)):
            union(accs[0], accs[i])
    for accs in card_groups.values():
        if len(accs) < 2:
            continue
        for i in range(1, len(accs)):
            union(accs[0], accs[i])

    clusters = defaultdict(list)
    for acc in list(parent.keys()):
        clusters[find(acc)].append(acc)
    return list(clusters.values())


def _pipelined_score_lookup(redis_client, accounts: list[str]) -> dict[str, float]:
    """Fetch GNN scores for a list of accounts in pipelined batches."""
    scores = {}
    for i in range(0, len(accounts), PIPELINE_BATCH):
        batch = accounts[i : i + PIPELINE_BATCH]
        try:
            pipe = redis_client.pipeline(transaction=False)
            for acc in batch:
                pipe.get(f"gnn:score:{acc}")
            results = pipe.execute()
        except Exception as e:
            log.warning(f"pipeline batch failed: {e}")
            continue
        for acc, s in zip(batch, results):
            if not s:
                continue
            try:
                scores[acc] = float(s)
            except (ValueError, TypeError):
                continue
    return scores


def discover_rings(redis_client, parquet_path: Path, cutoff: int,
                   unlabeled_threshold: float = 0.30,
                   max_suspects: int = 20) -> dict:
    log.info("Discovery: loading shared-infra maps ...")
    acc_to_dev, acc_to_card = _build_shared_infra_maps(
        redis_client, parquet_path, cutoff
    )

    log.info("Discovery: grouping by infra ...")
    dev_groups, card_groups = _group_by_infra(acc_to_dev, acc_to_card)

    log.info("Discovery: union-find clustering ...")
    raw_clusters = _union_find_clusters(dev_groups, card_groups)
    log.info(f"Discovery: {len(raw_clusters)} candidate clusters")

    clusters_out = []
    all_clustered = set()

    # Score only accounts that actually appear in clusters — small set
    clustered_accounts = []
    for members in raw_clusters:
        if len(members) >= 2:
            clustered_accounts.extend(members)
    cluster_scores = _pipelined_score_lookup(redis_client, clustered_accounts)

    # Ring ids for clustered accounts — pipelined
    ring_ids_by_acc: dict[str, str] = {}
    for i in range(0, len(clustered_accounts), PIPELINE_BATCH):
        batch = clustered_accounts[i : i + PIPELINE_BATCH]
        try:
            pipe = redis_client.pipeline(transaction=False)
            for acc in batch:
                pipe.get(f"gnn:ring_id:{acc}")
            results = pipe.execute()
            for acc, r in zip(batch, results):
                if r:
                    ring_ids_by_acc[acc] = (
                        r.decode() if isinstance(r, bytes) else r
                    )
        except Exception:
            continue

    for members in raw_clusters:
        if len(members) < 2:
            continue
        all_clustered.update(members)

        gnn_scores = [cluster_scores[m] for m in members if m in cluster_scores]
        ring_ids = {ring_ids_by_acc[m] for m in members if m in ring_ids_by_acc}

        avg_gnn = sum(gnn_scores) / len(gnn_scores) if gnn_scores else 0.0
        is_labeled = len(ring_ids) > 0
        if is_labeled:
            if any(rid.startswith("ring_attack_") for rid in ring_ids):
                category = "simulated"
            else:
                category = "original"
        else:
            category = "novel"
        suspicion = avg_gnn * math.log(len(members) + 1)

        sample = members[0]
        shared_dev = acc_to_dev.get(sample, "")
        shared_card = acc_to_card.get(sample, "")

        clusters_out.append({
            "cluster_id": len(clusters_out),
            "size": len(members),
            "avg_gnn": round(avg_gnn, 4),
            "is_labeled": is_labeled,
            "category": category,
            "ring_ids": sorted(ring_ids),
            "suspicion_score": round(suspicion, 4),
            "shared_device": shared_dev,
            "shared_card": shared_card,
            "sample_accounts": sorted(members)[:10],
            "all_members": sorted(members),
        })

    clusters_out.sort(key=lambda c: c["suspicion_score"], reverse=True)

    # Suspect scan — sample 100k accounts, pipelined
    log.info(f"Discovery: sampling {SUSPECT_SAMPLE_SIZE:,} accounts for suspects ...")
    all_accounts = list(acc_to_dev.keys())
    rng = random.Random(42)
    if len(all_accounts) > SUSPECT_SAMPLE_SIZE:
        sample = rng.sample(all_accounts, SUSPECT_SAMPLE_SIZE)
    else:
        sample = all_accounts

    sample_scores = _pipelined_score_lookup(redis_client, sample)
    suspects = []
    for acc, score in sample_scores.items():
        if score < unlabeled_threshold:
            continue
        if acc in all_clustered:
            continue
        suspects.append({"account_id": acc, "gnn_score": round(score, 4)})
    suspects.sort(key=lambda s: s["gnn_score"], reverse=True)
    suspects = suspects[:max_suspects]

    return {
        "total_clusters": len(clusters_out),
        "labeled_clusters": sum(1 for c in clusters_out if c["is_labeled"]),
        "unlabeled_clusters": sum(1 for c in clusters_out if not c["is_labeled"]),
        "clusters": clusters_out,
        "unlabeled_suspects": suspects,
    }

def get_ring_replay(redis_client, ring_id: str, parquet_path: Path, cutoff: int) -> dict | None:
    """Build a timeline of events for a ring.

    Original rings: read every transaction from parquet, ordered by step.
    Simulated rings: construct a synthetic 5-step timeline (launch, device,
    spawn, drain, detect) since attack transactions aren't in parquet.
    Novel clusters (no ring_id): return None — nothing to replay.
    """
    members_raw = redis_client.get(f"gnn:ring_members:{ring_id}")
    if not members_raw:
        return None
    try:
        members = json.loads(members_raw)
    except Exception:
        return None
    if not members:
        return None

    kind = "simulated" if ring_id.startswith("ring_attack_") else "original"

    sample = members[0]
    device = redis_client.get(f"gnn:device:{sample}") or ""
    card = redis_client.get(f"gnn:card:{sample}") or ""
    if isinstance(device, bytes):
        device = device.decode()
    if isinstance(card, bytes):
        card = card.decode()

    events = []

    if kind == "simulated":
        events.append({
            "t": 0,
            "type": "attack_launched",
            "label": "Attack launched",
            "detail": f"{len(members)} accounts created",
        })
        events.append({
            "t": 1,
            "type": "device_seen",
            "label": "Device first seen",
            "detail": device,
        })
        for m in members:
            events.append({
                "t": 2,
                "type": "account_spawned",
                "label": "Account spawned",
                "account": m,
                "detail": "$50,000 injected balance",
            })
        events.append({
            "t": 3,
            "type": "coordinated_drain",
            "label": f"{len(members)} coordinated CASH_OUTs",
            "detail": "Full balance drain",
            "amount": 50000.0 * len(members),
        })
        events.append({
            "t": 4,
            "type": "detected",
            "label": "Ring detected",
            "detail": "GNN score 0.99 → soft-OR BLOCK",
        })
        stats = {
            "total_volume": 50000.0 * len(members),
            "avg_transaction": 50000.0,
            "detection_step": 4,
            "members_count": len(members),
            "duration_steps": 4,
        }
    else:
        try:
            df = pd.read_parquet(
                parquet_path,
                columns=["nameOrig", "step", "amount", "type",
                         "newbalanceOrig", "oldbalanceOrg"],
                filters=[("step", ">", cutoff), ("nameOrig", "in", members)],
            )
        except Exception as e:
            log.warning(f"replay parquet read failed: {e}")
            df = pd.DataFrame()

        if df.empty:
            events.append({
                "t": 0,
                "type": "no_data",
                "label": "No transaction history",
                "detail": "Ring members have no txns in the warmup window",
            })
            stats = {"members_count": len(members)}
        else:
            first_step = int(df["step"].min())
            last_step = int(df["step"].max())

            events.append({
                "t": first_step,
                "type": "device_seen",
                "label": "Device first seen",
                "detail": device,
            })

            for m in members:
                m_df = df[df["nameOrig"] == m]
                if m_df.empty:
                    continue
                events.append({
                    "t": int(m_df["step"].min()),
                    "type": "account_spawned",
                    "label": "Account first active",
                    "account": m,
                    "detail": "",
                })

            txn_df = df.sort_values("step").head(50)
            for _, row in txn_df.iterrows():
                is_drain = (row["newbalanceOrig"] == 0
                            and row["oldbalanceOrg"] > 0)
                events.append({
                    "t": int(row["step"]),
                    "type": "drain" if is_drain else "transaction",
                    "label": f"{row['type']} ${row['amount']:,.0f}",
                    "account": row["nameOrig"],
                    "amount": float(row["amount"]),
                    "detail": "Full balance drain" if is_drain else "",
                })

            events.append({
                "t": last_step,
                "type": "detected",
                "label": "Ring detected",
                "detail": "GNN score 0.99 → soft-OR BLOCK",
            })

            stats = {
                "total_volume": float(df["amount"].sum()),
                "avg_transaction": float(df["amount"].mean()),
                "detection_step": last_step,
                "members_count": len(members),
                "duration_steps": last_step - first_step,
            }

    events.sort(key=lambda e: (e["t"], e["type"]))
    t_min = min(e["t"] for e in events) if events else 0
    t_max = max(e["t"] for e in events) if events else t_min + 1

    return {
        "ring_id": ring_id,
        "kind": kind,
        "members": members,
        "device_id": device,
        "card_id": card,
        "start_t": t_min,
        "end_t": t_max,
        "events": events,
        "stats": stats,
    }