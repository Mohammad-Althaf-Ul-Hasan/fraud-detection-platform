"""Check the latest drift report; trigger retraining if drift exceeds threshold.

Rules:
  * If drift_share <= DRIFT_THRESHOLD (0.50): skip with reason "no_drift".
  * If last successful retrain < DRIFT_RETRAIN_COOLDOWN_HOURS (24h) ago: skip
    with reason "cooldown".
  * Otherwise: run scripts/train_xgb.py, log result, and (only with
    --auto-reload) POST /reload to the running service.

Every decision is appended to reports/retrain_log.jsonl for auditing.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from common.schema import (  # noqa: E402
    DRIFT_LATEST_JSON, DRIFT_RETRAIN_LOG,
    DRIFT_THRESHOLD, DRIFT_RETRAIN_COOLDOWN_HOURS,
)

SERVICE_URL = "http://127.0.0.1:8000"
TRAIN_XGB   = PROJECT_ROOT / "scripts" / "train_xgb.py"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_decision(entry: dict) -> None:
    log_path = PROJECT_ROOT / DRIFT_RETRAIN_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"  logged -> {log_path.relative_to(PROJECT_ROOT)}")


def last_retrain_hours_ago() -> float | None:
    log_path = PROJECT_ROOT / DRIFT_RETRAIN_LOG
    if not log_path.exists():
        return None
    last = None
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("decision") == "retrain" and entry.get("status") == "success":
                    last = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            except Exception:
                continue
    if last is None:
        return None
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600.0


def read_latest_drift() -> dict | None:
    path = PROJECT_ROOT / DRIFT_LATEST_JSON
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARN: cannot parse {path}: {e}")
        return None


def call_reload() -> dict:
    try:
        r = httpx.post(f"{SERVICE_URL}/reload", timeout=60.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="log the decision but do NOT run train_xgb.py")
    ap.add_argument("--auto-reload", action="store_true",
                    help="after a successful retrain, POST /reload to the service")
    ap.add_argument("--force", action="store_true",
                    help="ignore drift + cooldown checks and retrain immediately")
    args = ap.parse_args()

    print("=== Retrain trigger ===")
    drift = read_latest_drift()
    if drift is None and not args.force:
        log_decision({
            "timestamp": now_iso(),
            "decision": "skip",
            "reason": "no_drift_report",
            "dry_run": args.dry_run,
        })
        print("  no drift report found — nothing to do")
        return 0

    drift_share = drift.get("drift_share", 0.0) if drift else 0.0
    print(f"  drift_share        : {drift_share:.4f}")
    print(f"  threshold          : {DRIFT_THRESHOLD}")
    print(f"  simulated          : {drift.get('simulated_drift') if drift else '-'}")

    if not args.force:
        if drift_share <= DRIFT_THRESHOLD:
            log_decision({
                "timestamp": now_iso(),
                "decision": "skip",
                "reason": "no_drift",
                "drift_share": drift_share,
                "threshold": DRIFT_THRESHOLD,
                "dry_run": args.dry_run,
            })
            print("  -> skip: drift below threshold")
            return 0

        hours = last_retrain_hours_ago()
        if hours is not None and hours < DRIFT_RETRAIN_COOLDOWN_HOURS:
            log_decision({
                "timestamp": now_iso(),
                "decision": "skip",
                "reason": "cooldown",
                "hours_since_last_retrain": round(hours, 2),
                "cooldown_hours": DRIFT_RETRAIN_COOLDOWN_HOURS,
                "drift_share": drift_share,
                "dry_run": args.dry_run,
            })
            print(f"  -> skip: last retrain was {hours:.1f}h ago "
                  f"(cooldown={DRIFT_RETRAIN_COOLDOWN_HOURS}h)")
            return 0

    # Decision: retrain
    print(f"  -> RETRAIN  (drift {drift_share:.3f} > {DRIFT_THRESHOLD}, "
          f"forced={args.force})")

    if args.dry_run:
        log_decision({
            "timestamp": now_iso(),
            "decision": "retrain",
            "status": "dry_run",
            "drift_share": drift_share,
            "threshold": DRIFT_THRESHOLD,
            "dry_run": True,
        })
        print("  dry-run: skipped actual training")
        return 0

    if not TRAIN_XGB.exists():
        print(f"  ERROR: {TRAIN_XGB} not found")
        return 1

    print(f"  launching: {sys.executable} {TRAIN_XGB.name}")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(TRAIN_XGB)],
            cwd=str(PROJECT_ROOT),
            capture_output=False,
            check=False,
        )
        elapsed = time.time() - t0
        if proc.returncode != 0:
            log_decision({
                "timestamp": now_iso(),
                "decision": "retrain",
                "status": "failed",
                "returncode": proc.returncode,
                "duration_seconds": round(elapsed, 1),
                "drift_share": drift_share,
            })
            print(f"  ERROR: train_xgb.py exited with {proc.returncode}")
            return 1
    except Exception as e:
        log_decision({
            "timestamp": now_iso(),
            "decision": "retrain",
            "status": "failed",
            "error": str(e),
            "drift_share": drift_share,
        })
        print(f"  ERROR launching train_xgb.py: {e}")
        return 1

    reload_result = None
    if args.auto_reload:
        print("  POST /reload ...")
        reload_result = call_reload()
        print(f"  reload result: {reload_result}")

    log_decision({
        "timestamp": now_iso(),
        "decision": "retrain",
        "status": "success",
        "duration_seconds": round(elapsed, 1),
        "drift_share": drift_share,
        "auto_reload": args.auto_reload,
        "reload_result": reload_result,
    })
    print(f"  retrain succeeded in {elapsed:.1f}s")
    if not args.auto_reload:
        print("  NOTE: service still running old model.")
        print("        Reload manually: curl -X POST http://127.0.0.1:8000/reload")
    return 0


if __name__ == "__main__":
    sys.exit(main())