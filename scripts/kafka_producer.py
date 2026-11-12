"""Replay the live window (last 20% of PaySim) into Kafka at a controlled TPS.

Payload includes raw fields plus `_truth_isFraud` for offline evaluation.
The consumer NEVER passes `_truth_isFraud` to the model — see scoring_service.py.

Producer samples a random subset when --limit is smaller than the live window,
so repeated invocations send fresh txn_ids (avoids dedupe blocking tests).
"""
import argparse
import json
import time
from pathlib import Path
import pandas as pd
from kafka import KafkaProducer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARQUET = PROJECT_ROOT / "data" / "processed" / "features.parquet"
CUTOFF_FILE = PROJECT_ROOT / "data" / "processed" / "warmup_cutoff.txt"
TOPIC = "raw_transactions"

PAYLOAD_COLS = [
    "txn_id", "step", "type", "amount",
    "nameOrig", "oldbalanceOrg", "newbalanceOrig",
    "nameDest", "oldbalanceDest", "newbalanceDest",
    "timestamp", "_truth_isFraud",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tps", type=int, default=50, help="transactions / second")
    ap.add_argument("--limit", type=int, default=5000,
                    help="max rows to send; 0 = all live rows")
    ap.add_argument("--bootstrap", default="localhost:9092")
    args = ap.parse_args()

    if not CUTOFF_FILE.exists():
        raise SystemExit(f"Missing {CUTOFF_FILE}. Run materialize_warmup.py first.")

    # --- Load full live window (this is the line that was missing) ---
    df = pd.read_parquet(PARQUET)
    cutoff = int(CUTOFF_FILE.read_text().strip())
    live = df[df["step"] > cutoff].reset_index(drop=True).copy()
    print(f"Live window: {len(live):,} rows (step > {cutoff})")

    # Stable txn_id tied to the row's position in the live window
    live["txn_id"] = live.index.astype(str)
    live["timestamp"] = live["timestamp"].astype(str)
    live["_truth_isFraud"] = live["isFraud"]

    # --- Random sample when --limit < live window; head() otherwise ---
    if args.limit > 0:
        if args.limit < len(live):
            live = live.sample(n=args.limit, random_state=None).reset_index(drop=True)
        else:
            live = live.head(args.limit)
    print(f"Sending {len(live):,} txns at {args.tps} TPS")

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap,
        value_serializer=lambda v: json.dumps(v, default=str).encode(),
        acks=1, linger_ms=5,
    )

    interval = 1.0 / args.tps
    t0 = time.time()
    for i, row in live.iterrows():
        producer.send(TOPIC, {c: row[c] for c in PAYLOAD_COLS})
        if (i + 1) % 500 == 0:
            el = time.time() - t0
            print(f"  sent {i+1:,}/{len(live):,}  ({i+1/el:.1f} tps)")
        time.sleep(interval)

    producer.flush()
    el = time.time() - t0
    print(f"Done. Sent {len(live):,} in {el:.1f}s ({len(live)/el:.1f} tps)")


if __name__ == "__main__":
    main()