"""Measure /predict latency end-to-end (HTTP + model + Feast lookup on miss)."""
import argparse
import statistics
import time
from pathlib import Path

import httpx
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARQUET = PROJECT_ROOT / "data" / "processed" / "features.parquet"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/predict")
    ap.add_argument("--n", type=int, default=500)
    args = ap.parse_args()

    df = pd.read_parquet(PARQUET).sample(args.n, random_state=42)
    lat = []
    with httpx.Client(timeout=10.0) as client:
        for i, row in df.iterrows():
            payload = {
                "txn_id": str(i),
                "step": int(row["step"]),
                "type": row["type"],
                "amount": float(row["amount"]),
                "nameOrig": row["nameOrig"],
                "oldbalanceOrg": float(row["oldbalanceOrg"]),
                "newbalanceOrig": float(row["newbalanceOrig"]),
                "nameDest": row["nameDest"],
                "oldbalanceDest": float(row["oldbalanceDest"]),
                "newbalanceDest": float(row["newbalanceDest"]),
            }
            t0 = time.perf_counter()
            r = client.post(args.url, json=payload)
            lat.append((time.perf_counter() - t0) * 1000.0)
            if r.status_code != 200:
                print(f"ERR {r.status_code}: {r.text}")
                break

    if not lat:
        return
    srt = sorted(lat)
    print(f"\n=== /predict benchmark ({len(lat)} requests) ===")
    print(f"  mean: {statistics.mean(lat):6.2f} ms")
    print(f"  p50:  {srt[len(srt)//2]:6.2f} ms")
    print(f"  p95:  {srt[int(0.95*len(srt))]:6.2f} ms")
    print(f"  p99:  {srt[int(0.99*len(srt))]:6.2f} ms")
    print(f"  max:  {srt[-1]:6.2f} ms")


if __name__ == "__main__":
    main()