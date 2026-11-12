"""FastAPI scoring service with embedded Kafka consumer + GNN blend.

P1 production foundations:
  * All state in Redis (recent, txn_index, samples, latencies, counters, rings cache).
  * /predict honors X-Idempotency-Key header (24h cache, no double-score).
  * Consumer dedupes on txn_id via SET NX scored:{txn_id} (7-day TTL).
  * Model calibration: isotonic regression on XGB scores if calibrator exists.
  * Graceful shutdown drains in-flight HTTP, stops consumer, flushes Kafka producer.
  * Kafka broker + Redis host/port read from env vars (see .env.example).

P2 enterprise features:
  * API key auth on write endpoints (require_api_key dependency).
  * Per-key sliding-window rate limiting (check_rate_limit dependency).
  * Circuit breakers around Feast and Redis (fall back gracefully).
  * X-Trace-Id header injection on every response (TraceMiddleware).
"""

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="redis")
warnings.filterwarnings("ignore", message="value_serializer does not implement")
warnings.filterwarnings("ignore", message="value_deserializer does not implement")
warnings.filterwarnings("ignore", message=".*does not implement kafka.serializer.*")

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib

import numpy as np
import mlflow
import mlflow.xgboost
import xgboost as xgb
import redis as redis_lib
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from kafka import KafkaConsumer, KafkaProducer
from feast import FeatureStore

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.enterprise import (
    require_api_key,
    check_rate_limit,
    redis_breaker,
    feast_breaker,
    TraceMiddleware,
    API_KEYS,
    RATE_LIMIT_PER_SEC,
)

from prometheus_client import make_asgi_app

from services.metrics import record_prediction, record_kafka_consumed, record_kafka_duplicate, record_case_persisted, set_model_info, set_drift_share
from services.llm_client import stream_narrative
from services.discovery import discover_rings, get_ring_replay

from common.schema import (
    FEATURE_COLS, DEFAULT_THRESHOLD, TOPIC_RAW, TOPIC_SCORED,
    GNM_SCORE_PREFIX, GNM_RING_ID_PREFIX,
    GNM_DEVICE_PREFIX, GNM_CARD_PREFIX, GNM_RING_MEMBERS_PREFIX,
    REDIS_HOST, REDIS_PORT, KAFKA_BROKER,
    DRIFT_LATEST_JSON, DRIFT_THRESHOLD, DRIFT_MAX_BUFFER,
    REDIS_RECENT_ZSET, REDIS_TXN_PREFIX, REDIS_SAMPLES_LIST,
    REDIS_LATENCIES_LIST, REDIS_COUNTERS_HASH,
    REDIS_IDEM_PREFIX, REDIS_SCORED_PREFIX, REDIS_RINGS_CACHE_KEY,
    REDIS_TXN_TTL, REDIS_IDEM_TTL, REDIS_SCORED_TTL, REDIS_RINGS_CACHE_TTL,
    REDIS_FEATURES_PREFIX, REDIS_FEATURES_TTL,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MLFLOW_DB = PROJECT_ROOT / "mlflow.db"
MLFLOW_URI = f"sqlite:///{MLFLOW_DB.as_posix()}"
EXPERIMENT = "fraud-detection-paysim"
EXPERIMENT_GNN = "fraud-detection-gnn"
FEAST_REPO = str(PROJECT_ROOT / "feature_repo")
CASES_DB = PROJECT_ROOT / "data" / "cases.db"
CALIBRATOR_PATH = PROJECT_ROOT / "models" / "calibrator.pkl"
CALIBRATOR_META_PATH = PROJECT_ROOT / "models" / "calibrator_meta.json"

BLEND_MODE = "soft_or"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scoring")


def _hash12(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:12]


# ---------- Redis-backed state helpers --------------------------------------

def _incr(metric: str, amount: int = 1) -> None:
    """Non-fatal counter increment."""
    try:
        S.redis.hincrby(REDIS_COUNTERS_HASH, metric, amount)
    except Exception:
        pass


def _read_counters() -> dict:
    defaults = {
        "consumed": 0, "scored": 0,
        "predicted_fraud": 0, "actual_fraud": 0, "true_positive": 0,
        "gnn_hits": 0, "gnn_misses": 0, "duplicates_skipped": 0,
    }
    try:
        raw = S.redis.hgetall(REDIS_COUNTERS_HASH)
        for k, v in raw.items():
            try:
                defaults[k] = int(v)
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return defaults


def _push_recent(txn_id: str, timestamp: float, payload_json: str) -> None:
    """ZADD to alerts:recent + SET per-txn payload with TTL."""
    try:
        S.redis.zadd(REDIS_RECENT_ZSET, {txn_id: timestamp})
        S.redis.set(f"{REDIS_TXN_PREFIX}{txn_id}", payload_json, ex=REDIS_TXN_TTL)
    except Exception:
        pass


def _read_recent(n: int = 20) -> list:
    try:
        ids = S.redis.zrevrange(REDIS_RECENT_ZSET, 0, n - 1)
        if not ids:
            return []
        pipe = S.redis.pipeline()
        for tid in ids:
            pipe.get(f"{REDIS_TXN_PREFIX}{tid}")
        raw = pipe.execute()
    except Exception as e:
        log.warning(f"recent read failed: {e}")
        return []
    out = []
    for r in raw:
        if not r:
            continue
        try:
            out.append(json.loads(r))
        except json.JSONDecodeError:
            pass
    return out


# ---------- SQLite cases persistence ----------------------------------------

def _init_cases_db():
    CASES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CASES_DB, check_same_thread=False)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                txn_id TEXT PRIMARY KEY,
                nameOrig TEXT, nameDest TEXT, amount REAL, type TEXT, step INTEGER,
                xgb_probability REAL, gnn_probability REAL, fraud_probability REAL,
                decision TEXT, threshold REAL, is_high_risk INTEGER,
                truth_isFraud INTEGER, created_at TEXT,
                label TEXT, label_by TEXT, label_at TEXT, notes TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_label ON cases(label)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_created ON cases(created_at)")
        conn.commit()
    finally:
        conn.close()


def _persist_case(result: dict, truth: int):
    prob = float(result["fraud_probability"])
    thr = float(result["threshold"])
    is_high_risk = 1 if prob >= thr * 0.5 else 0
    if result["decision"] != "BLOCK" and not is_high_risk:
        return
    record_case_persisted(result["decision"], is_high_risk)    
    conn = sqlite3.connect(CASES_DB, check_same_thread=False)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO cases
            (txn_id, nameOrig, nameDest, amount, type, step,
             xgb_probability, gnn_probability, fraud_probability, decision,
             threshold, is_high_risk, truth_isFraud, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result["txn_id"], result["nameOrig"], result["nameDest"],
            result["amount"], result["type"], result["step"],
            result["xgb_probability"], result["gnn_probability"],
            result["fraud_probability"], result["decision"],
            result["threshold"], is_high_risk, truth,
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
    finally:
        conn.close()


_init_cases_db()


# ---------- WebSocket connection manager ------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active = []
        self.lock = asyncio.Lock()

    async def connect(self, ws):
        await ws.accept()
        async with self.lock:
            self.active.append(ws)
        log.info(f"WS client connected. Total={len(self.active)}")

    async def disconnect(self, ws):
        async with self.lock:
            if ws in self.active:
                self.active.remove(ws)
        log.info(f"WS client disconnected. Total={len(self.active)}")

    async def broadcast(self, data: dict):
        if not self.active:
            return
        async with self.lock:
            dead = []
            for ws in self.active:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                try:
                    self.active.remove(ws)
                except ValueError:
                    pass


manager = ConnectionManager()
_loop = None


# ---------- per-account velocity state --------------------------------------

class AccountState:
    __slots__ = ("recent", "total_count", "total_sum", "max_amount")

    def __init__(self):
        self.recent = deque()
        self.total_count = 0
        self.total_sum = 0.0
        self.max_amount = 0.0

    def add(self, step: int, amount: float) -> None:
        self.recent.append((step, amount))
        self.total_count += 1
        self.total_sum += amount
        if amount > self.max_amount:
            self.max_amount = amount
        cutoff = step - 24
        while self.recent and self.recent[0][0] <= cutoff:
            self.recent.popleft()

    def features(self, current_step: int, current_amount: float) -> dict:
        f = {}
        for w in (1, 6, 24):
            c, s = 0, 0.0
            cutoff = current_step - w
            for step_i, amt_i in self.recent:
                if step_i > cutoff:
                    c += 1
                    s += amt_i
            f[f"orig_count_{w}h"] = c
            f[f"orig_sum_{w}h"] = s
        avg = self.total_sum / self.total_count if self.total_count else 0.0
        f["orig_prior_avg_amount"] = avg
        f["orig_prior_max_amount"] = self.max_amount
        f["orig_amount_vs_avg"] = current_amount / (avg + 1.0)
        f["orig_amount_vs_max"] = current_amount / (self.max_amount + 1.0)
        return f


class StateCache:
    """Per-account velocity cache. In-memory because it's per-process state;
    Feast lookup is the cold-start path, in-memory cache is the hot path."""

    def __init__(self, store):
        self.store = store
        self.cache = {}

    def get(self, account_id: str) -> AccountState:
        if account_id in self.cache:
            return self.cache[account_id]
        state = AccountState()
        try:
            def _feast_lookup():
                return self.store.get_online_features(
                    features=[
                        "account_features:orig_count_24h",
                        "account_features:orig_prior_avg_amount",
                        "account_features:orig_prior_max_amount",
                    ],
                    entity_rows=[{"nameOrig": account_id}],
                ).to_dict()

            resp = feast_breaker.call(_feast_lookup, fallback=lambda: {})
            if resp:
                cnt = int(resp.get("orig_count_24h", [0])[0] or 0)
                avg = float(resp.get("orig_prior_avg_amount", [0])[0] or 0.0)
                mx = float(resp.get("orig_prior_max_amount", [0])[0] or 0.0)
                state.total_count = cnt
                state.total_sum = avg * cnt
                state.max_amount = mx
        except Exception as e:
            log.debug(f"Feast miss for {account_id}: {e}")
        self.cache[account_id] = state
        return state


# ---------- feature vector ---------------------------------------------------

def build_feature_row(txn: dict, orig_feats: dict, dest_feats: dict) -> dict:
    amount = float(txn["amount"])
    old_o = float(txn["oldbalanceOrg"])
    old_d = float(txn["oldbalanceDest"])
    t = txn["type"]

    row = {
        "amount": amount,
        "oldbalanceOrg": old_o,
        "oldbalanceDest": old_d,
        "amount_to_balance_ratio": amount / (old_o + 1.0),
        "dest_is_merchant": int(txn["nameDest"].startswith("M")),
        "hour_of_day": int(txn["step"] % 24),
        "is_transfer": int(t == "TRANSFER"),
        "is_cash_out": int(t == "CASH_OUT"),
        "is_payment": int(t == "PAYMENT"),
        "is_cash_in": int(t == "CASH_IN"),
        "is_debit": int(t == "DEBIT"),
    }
    row.update(orig_feats)
    for k, v in dest_feats.items():
        row[k.replace("orig_", "dest_")] = v
    return row


def row_to_matrix(row: dict) -> np.ndarray:
    missing = [c for c in FEATURE_COLS if c not in row]
    if missing:
        raise ValueError(f"Feature row missing {missing}")
    return np.array([row[c] for c in FEATURE_COLS], dtype=np.float32).reshape(1, -1)


# ---------- app state --------------------------------------------------------

class AppState:
    def __init__(self):
        self.model = None
        self.model_run_id = None
        self.threshold_raw = DEFAULT_THRESHOLD
        self.threshold = DEFAULT_THRESHOLD
        self.calibrator = None
        self.calibrator_meta = {}
        self.feature_store = None
        self.state_cache = None
        self.dest_cache = None
        self.redis = None
        self.kafka_consumer = None
        self.kafka_producer = None
        self.consumer_thread = None
        self.model_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self.started_at = time.time()


S = AppState()


def load_latest_model():
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.tracking.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT)
    if exp is None:
        raise RuntimeError(f"MLflow experiment '{EXPERIMENT}' not found.")
    all_runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        order_by=["start_time DESC"],
    )
    xgb_runs = [r for r in all_runs if "pr_auc" in r.data.metrics]
    if not xgb_runs:
        raise RuntimeError(f"No XGBoost runs with 'pr_auc' in '{EXPERIMENT}'.")
    run = xgb_runs[0]
    run_id = run.info.run_id
    log.info(f"Selected XGB run {run_id} (pr_auc={run.data.metrics['pr_auc']:.4f})")

    model = None
    try:
        model = mlflow.xgboost.load_model(f"runs:/{run_id}/model")
        log.info("Loaded via runs:/ URI")
    except Exception as e:
        log.warning(f"runs:/ URI failed ({e}); trying local path")
        local = PROJECT_ROOT / "mlruns" / exp.experiment_id / run_id / "artifacts" / "model"
        if not local.exists():
            raise RuntimeError(f"Model artifacts missing at {local}.")
        model = mlflow.xgboost.load_model(str(local))
        log.info(f"Loaded from {local}")

    threshold_raw = float(run.data.metrics.get("best_threshold", DEFAULT_THRESHOLD))
    log.info(f"Threshold (raw): {threshold_raw:.4f}")
    return model, run_id, threshold_raw


def _load_calibrator():
    if not CALIBRATOR_PATH.exists():
        return None, {}
    try:
        import joblib
        cal = joblib.load(CALIBRATOR_PATH)
        meta = {}
        if CALIBRATOR_META_PATH.exists():
            meta = json.loads(CALIBRATOR_META_PATH.read_text())
        thr_cal = meta.get("threshold_calibrated")
        parent = meta.get("parent_run_id", "")
        parent_short = parent[:12] if parent else "?"
        log.info(
            f"Calibrator loaded (isotonic). threshold_calibrated={thr_cal} "
            f"parent_run={parent_short}"
        )
        return cal, meta
    except Exception as e:
        log.warning(f"Failed to load calibrator: {e}")
        return None, {}


def score_one(txn: dict) -> dict:
    t0 = time.perf_counter()
    account = txn["nameOrig"]
    dest = txn["nameDest"]

    orig_state = S.state_cache.get(account)
    dest_state = S.dest_cache.get(dest) if not dest.startswith("M") else AccountState()

    orig_feats = orig_state.features(txn["step"], float(txn["amount"]))
    dest_feats = dest_state.features(txn["step"], float(txn["amount"]))

    feature_row = build_feature_row(txn, orig_feats, dest_feats)
    try:
        S.redis.set(
            f"{REDIS_FEATURES_PREFIX}{txn['txn_id']}",
            json.dumps({c: float(feature_row[c]) for c in FEATURE_COLS}),
            ex=REDIS_FEATURES_TTL,
        )
    except Exception:
        pass
    X = row_to_matrix(feature_row)
    p_xgb_raw = float(S.model.predict_proba(X)[0, 1])

    if S.calibrator is not None:
        try:
            p_xgb = float(S.calibrator.predict([p_xgb_raw])[0])
            p_xgb = max(0.0, min(1.0, p_xgb))
        except Exception:
            p_xgb = p_xgb_raw
    else:
        p_xgb = p_xgb_raw

    gnn_raw = redis_breaker.call(
        lambda: S.redis.get(f"{GNM_SCORE_PREFIX}{account}"),
        fallback=lambda: None,
    )

    if gnn_raw is not None:
        p_gnn = float(gnn_raw)
        final = 1.0 - (1.0 - p_xgb) * (1.0 - p_gnn)
        _incr("gnn_hits")
    else:
        p_gnn = None
        final = p_xgb
        _incr("gnn_misses")

    latency_ms = (time.perf_counter() - t0) * 1000.0

    orig_state.add(txn["step"], float(txn["amount"]))
    if not dest.startswith("M"):
        dest_state.add(txn["step"], float(txn["amount"]))

    try:
        S.redis.lpush(
            REDIS_SAMPLES_LIST,
            json.dumps({c: float(feature_row[c]) for c in FEATURE_COLS}),
        )
    except Exception:
        pass

    try:
        S.redis.lpush(REDIS_LATENCIES_LIST, str(latency_ms))
    except Exception:
        pass

    decision = "BLOCK" if final >= S.threshold else "ALLOW"
    record_prediction(decision, latency_ms, final, p_gnn, S.model_run_id or "unknown")

    return {
        "txn_id": txn["txn_id"],
        "nameOrig": account,
        "nameDest": dest,
        "amount": float(txn["amount"]),
        "type": txn["type"],
        "step": int(txn["step"]),
        "oldbalanceOrg": float(txn["oldbalanceOrg"]),
        "newbalanceOrig": float(txn["newbalanceOrig"]),
        "oldbalanceDest": float(txn["oldbalanceDest"]),
        "newbalanceDest": float(txn["newbalanceDest"]),
        "fraud_probability": round(final, 6),
        "xgb_probability": round(p_xgb, 6),
        "xgb_raw": round(p_xgb_raw, 6),
        "gnn_probability": round(p_gnn, 6) if p_gnn is not None else None,
        "blend_mode": BLEND_MODE,
        "calibrated": S.calibrator is not None,
        "decision": decision,
        "threshold": S.threshold,
        "latency_ms": round(latency_ms, 3),
    }


def _broadcast_from_thread(result: dict):
    if _loop is None or not manager.active:
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.broadcast(result), _loop)
    except Exception:
        log.exception("ws broadcast failed")


def consume_loop():
    consumer = None
    while not S.shutdown_event.is_set():
        try:
            consumer = KafkaConsumer(
                TOPIC_RAW,
                bootstrap_servers=KAFKA_BROKER,
                bootstrap_timeout_ms=10000,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                auto_commit_interval_ms=1000,
                group_id="scoring-service",
                value_deserializer=lambda v: json.loads(v.decode()),
            )
            log.info(f"Consumer subscribed to {TOPIC_RAW} @ {KAFKA_BROKER}")
            break
        except Exception as e:
            log.warning(f"Kafka consumer bootstrap failed: {e} â€” retrying in 5s")
            if S.shutdown_event.wait(5):
                return
    if consumer is None:
        log.error("Consumer loop exiting without a working consumer")
        return

    producer = None
    while not S.shutdown_event.is_set():
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode(),
                linger_ms=5,
            )
            break
        except Exception as e:
            log.warning(f"Kafka producer bootstrap failed: {e} â€” retrying in 5s")
            if S.shutdown_event.wait(5):
                consumer.close()
                return
    if producer is None:
        log.error("Producer never came up â€” consumer loop exiting")
        consumer.close()
        return

    S.kafka_consumer = consumer
    S.kafka_producer = producer
    _incr("kafka_ready")

    while not S.shutdown_event.is_set():
        try:
            records = consumer.poll(timeout_ms=500)
            batch_scored = 0
            for _, msgs in records.items():
                for msg in msgs:
                    if S.shutdown_event.is_set():
                        break
                    txn = msg.value
                    txn_id = txn.get("txn_id", "")
                    _incr("consumed")
                    record_kafka_consumed()

                    try:
                        is_new = S.redis.set(
                            f"{REDIS_SCORED_PREFIX}{txn_id}", "1",
                            nx=True, ex=REDIS_SCORED_TTL,
                        )
                    except Exception:
                        is_new = True
                    if not is_new:
                        _incr("duplicates_skipped")
                        record_kafka_duplicate()
                        continue

                    try:
                        result = score_one(txn)
                    except Exception:
                        log.exception("scoring failed")
                        continue

                    _incr("scored")
                    batch_scored += 1

                    if result["decision"] == "BLOCK":
                        _incr("predicted_fraud")
                    truth = int(txn.get("_truth_isFraud", 0))
                    if truth == 1:
                        _incr("actual_fraud")
                        if result["decision"] == "BLOCK":
                            _incr("true_positive")
                    result["truth_isFraud"] = truth

                    now_ts = time.time()
                    _push_recent(txn_id, now_ts, json.dumps(result))

                    try:
                        _persist_case(result, truth)
                    except Exception:
                        log.exception("persist_case failed")
                    _broadcast_from_thread(result)
                    producer.send(TOPIC_SCORED, result)

            if batch_scored:
                try:
                    S.redis.ltrim(REDIS_LATENCIES_LIST, 0, 4999)
                    S.redis.ltrim(REDIS_SAMPLES_LIST, 0, DRIFT_MAX_BUFFER - 1)
                    S.redis.zremrangebyrank(REDIS_RECENT_ZSET, 0, -2001)
                except Exception:
                    pass

        except Exception:
            if S.shutdown_event.is_set():
                break
            log.exception("consumer loop error")
            time.sleep(1)

    log.info("Consumer loop exited.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    S.shutdown_event.clear()

    log.info("Starting scoring service ...")
    S.model, S.model_run_id, S.threshold_raw = load_latest_model()
    S.calibrator, S.calibrator_meta = _load_calibrator()
    if S.calibrator is not None and S.calibrator_meta.get("threshold_calibrated") is not None:
        S.threshold = float(S.calibrator_meta["threshold_calibrated"])
        log.info(
            f"Using calibrated threshold: {S.threshold:.4f} "
            f"(raw was {S.threshold_raw:.4f})"
        )
    else:
        S.threshold = S.threshold_raw

    S.feature_store = FeatureStore(repo_path=FEAST_REPO)
    S.state_cache = StateCache(S.feature_store)
    S.dest_cache = StateCache(S.feature_store)
    set_model_info(S.model_run_id or "unknown", S.calibrator is not None)
    S.redis = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    try:
        S.redis.ping()
        log.info(f"Redis online at {REDIS_HOST}:{REDIS_PORT}")
    except Exception as e:
        log.warning(f"Redis not reachable: {e}")

    S.consumer_thread = threading.Thread(
        target=consume_loop, daemon=True, name="kafka-consumer"
    )
    S.consumer_thread.start()
    log.info("Ready.")
    yield

    log.info("Shutting down gracefully ...")
    S.shutdown_event.set()
    if S.consumer_thread:
        S.consumer_thread.join(timeout=10)
        if S.consumer_thread.is_alive():
            log.warning("Consumer thread did not exit within 10s â€” forcing exit")
    if S.kafka_consumer:
        try:
            S.kafka_consumer.close(autocommit=True)
        except Exception as e:
            log.warning(f"consumer close: {e}")
    if S.kafka_producer:
        try:
            S.kafka_producer.flush(timeout=5)
            S.kafka_producer.close(timeout=5)
        except Exception as e:
            log.warning(f"producer close: {e}")
    log.info("Shutdown complete.")


app = FastAPI(title="Fraud Scoring Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(TraceMiddleware)
app.mount("/metrics", make_asgi_app())


class Txn(BaseModel):
    txn_id: str
    step: int
    type: str
    amount: float
    nameOrig: str
    oldbalanceOrg: float
    newbalanceOrig: float
    nameDest: str
    oldbalanceDest: float
    newbalanceDest: float


class Feedback(BaseModel):
    txn_id: str
    label: str
    label_by: str = "analyst"
    notes: str = ""


def read_latest_drift_summary():
    path = PROJECT_ROOT / DRIFT_LATEST_JSON
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Failed to read drift report {path}: {e}")
        return None


# ---------- endpoints -------------------------------------------------------

@app.post(
    "/predict",
    dependencies=[Depends(require_api_key), Depends(check_rate_limit)],
)
def predict(txn: Txn, idempotency_key: str = Header(None, alias="X-Idempotency-Key")):
    if S.model is None:
        raise HTTPException(503, "Model not loaded yet")
    if idempotency_key:
        try:
            cached = S.redis.get(f"{REDIS_IDEM_PREFIX}{idempotency_key}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
    try:
        result = score_one(txn.model_dump())
    except Exception as e:
        log.exception("predict failed")
        raise HTTPException(500, str(e))
    if idempotency_key:
        try:
            S.redis.set(
                f"{REDIS_IDEM_PREFIX}{idempotency_key}",
                json.dumps(result), ex=REDIS_IDEM_TTL,
            )
        except Exception:
            pass
    return result


@app.get("/health")
def health():
    ok = S.model is not None and S.state_cache is not None
    kafka_ok = S.kafka_consumer is not None and S.kafka_producer is not None
    try:
        redis_ok = S.redis.ping()
    except Exception:
        redis_ok = False

    if not ok or not redis_ok or not kafka_ok:
        overall = "degraded" if ok else "initializing"
    else:
        overall = "ok"

    drift = read_latest_drift_summary()
    try:
        fb_size = S.redis.llen(REDIS_SAMPLES_LIST)
    except Exception:
        fb_size = 0
    return {
        "status": overall,
        "kafka_connected": kafka_ok,
        "redis_connected": redis_ok,
        "model_loaded": ok,
        "model_run_id": S.model_run_id,
        "threshold": S.threshold,
        "threshold_raw": S.threshold_raw,
        "threshold_calibrated": (
            S.calibrator_meta.get("threshold_calibrated") if S.calibrator else None
        ),
        "calibrated": S.calibrator is not None,
        "blend_mode": BLEND_MODE,
        "drift_report_exists": drift is not None,
        "drift_generated_at": drift.get("generated_at") if drift else None,
        "feature_buffer_size": fb_size,
        "ws_clients": len(manager.active),
    }


@app.get("/stats")
def stats():
    try:
        lat_strings = S.redis.lrange(REDIS_LATENCIES_LIST, 0, -1)
        lat = sorted(float(x) for x in lat_strings)
    except Exception:
        lat = []
    if lat:
        mean = sum(lat) / len(lat)
        p50 = lat[len(lat) // 2]
        p95 = lat[int(0.95 * len(lat))]
        p99 = lat[int(0.99 * len(lat))]
    else:
        mean = p50 = p95 = p99 = 0.0
    c = _read_counters()
    prec = c["true_positive"] / c["predicted_fraud"] if c["predicted_fraud"] else 0.0
    rec = c["true_positive"] / c["actual_fraud"] if c["actual_fraud"] else 0.0
    try:
        fb_size = S.redis.llen(REDIS_SAMPLES_LIST)
    except Exception:
        fb_size = 0
    return {
        "counters": c,
        "latency_ms": {
            "mean": round(mean, 3), "p50": round(p50, 3),
            "p95": round(p95, 3), "p99": round(p99, 3),
            "n": len(lat),
        },
        "live_precision": round(prec, 4),
        "live_recall": round(rec, 4),
        "threshold": S.threshold,
        "threshold_raw": S.threshold_raw,
        "calibrated": S.calibrator is not None,
        "blend_mode": BLEND_MODE,
        "feature_buffer_size": fb_size,
        "ws_clients": len(manager.active),
    }


@app.get("/recent")
def recent(n: int = 20):
    return _read_recent(n)


@app.get("/graph/{account_id}")
def graph(account_id: str):
    if S.redis is None:
        raise HTTPException(503, "Redis not ready")
    try:
        ring_id = S.redis.get(f"{GNM_RING_ID_PREFIX}{account_id}") or ""
        if ring_id:
            device = S.redis.get(f"{GNM_DEVICE_PREFIX}{account_id}") or ""
            card = S.redis.get(f"{GNM_CARD_PREFIX}{account_id}") or ""
            members_json = S.redis.get(f"{GNM_RING_MEMBERS_PREFIX}{ring_id}")
            neighbors = json.loads(members_json) if members_json else []
        else:
            device = f"dev_{_hash12(account_id)}"
            card = f"card_{_hash12(account_id)}"
            neighbors = [account_id]
        gnn_score = S.redis.get(f"{GNM_SCORE_PREFIX}{account_id}")
    except Exception as e:
        raise HTTPException(503, f"Redis error: {e}")
    return {
        "account_id": account_id,
        "device_id": device,
        "card_id": card,
        "ring_id": ring_id,
        "is_ring_member": bool(ring_id),
        "neighbors": neighbors,
        "gnn_score": float(gnn_score) if gnn_score is not None else None,
    }


@app.get("/sample_features")
def sample_features(n: int = 2000):
    try:
        if S.redis.llen(REDIS_SAMPLES_LIST) == 0:
            raise HTTPException(404, "Feature buffer empty. Run producer first.")
        n = max(1, n)
        rows = S.redis.lrange(REDIS_SAMPLES_LIST, 0, n - 1)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"Redis error: {e}")
    clean = []
    for r in rows:
        try:
            clean.append(json.loads(r))
        except json.JSONDecodeError:
            pass
    return {"count": len(clean), "features": clean}


@app.get("/drift")
def drift():
    summary = read_latest_drift_summary()
    if summary is None:
        return {
            "report_exists": False,
            "message": "No drift report yet. Run scripts/drift_monitor.py.",
        }
    drifted = summary.get("drift_share", 0.0)
    set_drift_share(drifted)
    return {
        "report_exists": True,
        "generated_at": summary.get("generated_at"),
        "drift_share": drifted,
        "drifted_columns": summary.get("drifted_columns", 0),
        "total_columns": summary.get("total_columns", 0),
        "dataset_drift": summary.get("dataset_drift", False),
        "simulated_drift": summary.get("simulated_drift", False),
        "reference_rows": summary.get("reference_rows"),
        "current_rows": summary.get("current_rows"),
        "threshold": DRIFT_THRESHOLD,
        "retrain_recommended": drifted > DRIFT_THRESHOLD,
        "report_html_path": summary.get("report_html_path"),
        "report_json_path": summary.get("report_json_path"),
    }


@app.post("/reload", dependencies=[Depends(require_api_key)])
def reload_model_endpoint():
    if not S.model_lock.acquire(blocking=False):
        raise HTTPException(409, "Reload already in progress")
    try:
        new_model, new_run_id, new_threshold_raw = load_latest_model()
        new_cal, new_meta = _load_calibrator()
        old_run_id = S.model_run_id
        S.model = new_model
        S.model_run_id = new_run_id
        S.threshold_raw = new_threshold_raw
        S.calibrator = new_cal
        S.calibrator_meta = new_meta
        if new_cal is not None and new_meta.get("threshold_calibrated") is not None:
            S.threshold = float(new_meta["threshold_calibrated"])
        else:
            S.threshold = new_threshold_raw
        log.info(f"Model reloaded: {old_run_id} -> {new_run_id}")
        return {
            "status": "reloaded",
            "previous_run_id": old_run_id,
            "current_run_id": new_run_id,
            "threshold": S.threshold,
            "threshold_raw": S.threshold_raw,
            "calibrated": S.calibrator is not None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        log.exception("reload failed")
        raise HTTPException(500, f"Reload failed: {e}")
    finally:
        S.model_lock.release()


@app.post("/explain")
def explain(txn: Txn):
    if S.model is None:
        raise HTTPException(503, "Model not loaded")
    try:
        account = txn.nameOrig
        dest = txn.nameDest
        orig_state = S.state_cache.get(account)
        dest_state = S.dest_cache.get(dest) if not dest.startswith("M") else AccountState()
        orig_feats = orig_state.features(txn.step, float(txn.amount))
        dest_feats = dest_state.features(txn.step, float(txn.amount))
        feature_row = build_feature_row(txn.model_dump(), orig_feats, dest_feats)
        X = row_to_matrix(feature_row)

        p_xgb_raw = float(S.model.predict_proba(X)[0, 1])
        if S.calibrator is not None:
            try:
                p_xgb = float(S.calibrator.predict([p_xgb_raw])[0])
                p_xgb = max(0.0, min(1.0, p_xgb))
            except Exception:
                p_xgb = p_xgb_raw
        else:
            p_xgb = p_xgb_raw

        booster = S.model.get_booster()
        dm = xgb.DMatrix(X, feature_names=FEATURE_COLS)
        contribs = booster.predict(dm, pred_contribs=True)[0]
        shap_values = contribs[:-1]

        pairs = sorted(
            zip(FEATURE_COLS, shap_values),
            key=lambda kv: abs(float(kv[1])),
            reverse=True,
        )[:10]

        top = [
            {"name": name, "value": float(feature_row[name]), "shap_value": float(sv)}
            for name, sv in pairs
        ]

        try:
            gnn_raw = S.redis.get(f"{GNM_SCORE_PREFIX}{account}")
        except Exception:
            gnn_raw = None
        p_gnn = float(gnn_raw) if gnn_raw is not None else None
        final = (1.0 - (1.0 - p_xgb) * (1.0 - p_gnn)) if p_gnn is not None else p_xgb

        return {
            "txn_id": txn.txn_id,
            "xgb_probability": round(p_xgb, 6),
            "xgb_raw": round(p_xgb_raw, 6),
            "gnn_probability": round(p_gnn, 6) if p_gnn is not None else None,
            "fraud_probability": round(final, 6),
            "threshold": S.threshold,
            "calibrated": S.calibrator is not None,
            "decision": "BLOCK" if final >= S.threshold else "ALLOW",
            "top_features": top,
        }
    except Exception as e:
        log.exception("explain failed")
        raise HTTPException(500, str(e))

# ---------- Phase: LLM narrative endpoint -----------------------------------

from fastapi.responses import StreamingResponse

_NARRATIVE_LOCK = threading.Lock()
_NARRATIVE_STATE = {"count": 0, "reset_at": time.time() + 86400}
NARRATIVE_MAX_PER_DAY = int(os.getenv("MAX_NARRATIVES_PER_DAY", "500"))


def _narrative_rate_check() -> tuple[bool, int]:
    """Return (allowed, remaining_today)."""
    with _NARRATIVE_LOCK:
        now = time.time()
        if now >= _NARRATIVE_STATE["reset_at"]:
            _NARRATIVE_STATE["count"] = 0
            _NARRATIVE_STATE["reset_at"] = now + 86400
        remaining = NARRATIVE_MAX_PER_DAY - _NARRATIVE_STATE["count"]
        if remaining <= 0:
            return False, 0
        _NARRATIVE_STATE["count"] += 1
        return True, remaining - 1


class NarrativeRequest(BaseModel):
    txn_id: str
    regenerate: bool = False


def _build_narrative_prompt(txn_id: str, txn: dict) -> str:
    """Assemble a compact factual brief for the LLM."""
    lines = [f"Transaction ID: {txn_id}"]
    lines.append(f"Type: {txn.get('type', 'unknown')}")
    try:
        lines.append(f"Amount: ${float(txn.get('amount', 0)):,.2f}")
    except Exception:
        lines.append(f"Amount: {txn.get('amount')}")
    lines.append(f"Origin account: {txn.get('nameOrig', '?')}")
    lines.append(f"Destination account: {txn.get('nameDest', '?')}")
    try:
        lines.append(
            f"Final blended fraud probability: "
            f"{float(txn.get('fraud_probability', 0)):.4f}"
        )
        lines.append(
            f"XGBoost probability: {float(txn.get('xgb_probability', 0)):.4f}"
        )
        if txn.get("gnn_probability") is not None:
            lines.append(
                f"GNN (graph) probability: {float(txn.get('gnn_probability', 0)):.4f}"
            )
        lines.append(f"Decision threshold: {float(txn.get('threshold', 0.5)):.4f}")
    except Exception:
        pass
    lines.append(f"Decision: {txn.get('decision', 'ALLOW')}")

    # Graph context (best-effort)
    try:
        account = txn.get("nameOrig", "")
        if S.redis and account:
            ring_id = S.redis.get(f"{GNM_RING_ID_PREFIX}{account}")
            if ring_id:
                raw = S.redis.get(f"{GNM_RING_MEMBERS_PREFIX}{ring_id}")
                n = len(json.loads(raw)) if raw else 0
                lines.append(
                    f"Graph context: account belongs to ring {ring_id} "
                    f"with {n} members"
                )
            else:
                lines.append("Graph context: account is not part of any known ring")
    except Exception:
        pass

    lines.append("")
    lines.append(
        "Write a 3-4 sentence narrative explaining this decision. "
        "Mention which model (XGBoost, GNN, or the blend) drove the score. "
        "If ALLOW, note the primary factor keeping risk low. "
        "If BLOCK, note the primary factor driving risk. "
        "Do not speculate beyond the data above. No greetings, no headers, "
        "just prose."
    )
    return "\n".join(lines)


@app.post("/explain/narrative")
async def explain_narrative(body: NarrativeRequest):
    """Stream a plain-English case narrative as SSE.

    Frames:
      data: {"text": "<chunk>"}
      data: {"done": true}
      data: {"error": "<message>"}

    Cached narratives are returned instantly (fake-streamed with pacing)
    unless regenerate=true is set.
    """
    # Load txn
    txn = None
    try:
        cached = S.redis.get(f"{REDIS_TXN_PREFIX}{body.txn_id}")
        if cached:
            txn = json.loads(cached)
    except Exception:
        pass
    if txn is None:
        conn = sqlite3.connect(CASES_DB, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM cases WHERE txn_id = ?", (body.txn_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise HTTPException(
                404, f"txn {body.txn_id} not in buffer or cases DB"
            )
        txn = dict(row)

    cache_key = f"narrative:{body.txn_id}"

    # Fast path: cached narrative
    if not body.regenerate:
        try:
            cached_text = S.redis.get(cache_key)
        except Exception:
            cached_text = None
        if cached_text:
            async def stream_cached():
                words = cached_text.split(" ")
                for i, w in enumerate(words):
                    prefix = "" if i == 0 else " "
                    yield f"data: {json.dumps({'text': prefix + w})}\n\n"
                    if i % 3 == 0:
                        await asyncio.sleep(0.025)
                yield f"data: {json.dumps({'done': True, 'cached': True})}\n\n"
            return StreamingResponse(
                stream_cached(), media_type="text/event-stream"
            )

    # Rate limit
    allowed, remaining = _narrative_rate_check()
    if not allowed:
        raise HTTPException(
            429,
            f"Narrative rate limit reached ({NARRATIVE_MAX_PER_DAY}/day). "
            f"Set MAX_NARRATIVES_PER_DAY env var to raise it.",
        )

    prompt = _build_narrative_prompt(body.txn_id, txn)

    async def stream_fresh():
        full: list[str] = []
        try:
            async for chunk in stream_narrative(prompt):
                if not chunk:
                    continue
                full.append(chunk)
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            log.exception("llm streaming failed")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return
        narrative = "".join(full).strip()
        try:
            S.redis.setex(cache_key, 86400, narrative)
        except Exception:
            pass
        yield f"data: {json.dumps({'done': True, 'remaining_today': remaining})}\n\n"

    return StreamingResponse(
        stream_fresh(), media_type="text/event-stream"
    )

class CounterfactualRequest(BaseModel):
    txn_id: str
    amount: float | None = None
    orig_count_24h: int | None = None
    orig_prior_avg_amount: float | None = None
    dest_has_history: bool | None = None


@app.post("/explain/counterfactual")
def explain_counterfactual(body: CounterfactualRequest):
    """Re-score a txn with analyst-supplied feature overrides.
    Baseline response (no overrides) also returns the current feature values
    so the frontend can initialize sliders to the true values."""
    if S.model is None:
        raise HTTPException(503, "Model not loaded")

    # 1. Load the txn result from Redis, fall back to SQLite
    txn = None
    try:
        cached = S.redis.get(f"{REDIS_TXN_PREFIX}{body.txn_id}")
        if cached:
            txn = json.loads(cached)
    except Exception:
        pass
    if txn is None:
        conn = sqlite3.connect(CASES_DB, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM cases WHERE txn_id = ?", (body.txn_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise HTTPException(
                404, f"txn {body.txn_id} not in buffer or cases DB"
            )
        txn = dict(row)

    # 2. Load the cached feature row from Redis
    try:
        base_raw = S.redis.get(f"{REDIS_FEATURES_PREFIX}{body.txn_id}")
    except Exception:
        base_raw = None
    if not base_raw:
        raise HTTPException(
            404,
            f"Feature row for txn {body.txn_id} not cached. "
            f"Occurs after the txn ages out of the feature cache. "
            f"Replay and retry.",
        )
    base_row = json.loads(base_raw)

    # 3. Apply overrides
    row = dict(base_row)
    amount = (
        float(body.amount) if body.amount is not None else float(row["amount"])
    )
    old_o = float(row.get("oldbalanceOrg", 0) or 0)
    row["amount"] = amount
    row["amount_to_balance_ratio"] = amount / (old_o + 1.0)

    if body.orig_count_24h is not None:
        row["orig_count_24h"] = int(body.orig_count_24h)
        row["orig_count_6h"] = min(
            int(row.get("orig_count_6h", 0) or 0), int(body.orig_count_24h)
        )
        row["orig_count_1h"] = min(
            int(row.get("orig_count_1h", 0) or 0), int(body.orig_count_24h)
        )

    if body.orig_prior_avg_amount is not None:
        avg = float(body.orig_prior_avg_amount)
        row["orig_prior_avg_amount"] = avg
        for h in (1, 6, 24):
            c = int(row.get(f"orig_count_{h}h", 0) or 0)
            row[f"orig_sum_{h}h"] = c * avg
        row["orig_amount_vs_avg"] = amount / (avg + 1.0)

    if body.amount is not None:
        prior_avg = float(row.get("orig_prior_avg_amount", 0) or 0)
        prior_max = float(row.get("orig_prior_max_amount", 0) or 0)
        row["orig_amount_vs_avg"] = amount / (prior_avg + 1.0)
        row["orig_amount_vs_max"] = amount / (prior_max + 1.0)

    if body.dest_has_history is False:
        for h in (1, 6, 24):
            row[f"dest_count_{h}h"] = 0
            row[f"dest_sum_{h}h"] = 0.0
        row["dest_prior_avg_amount"] = 0.0
        row["dest_prior_max_amount"] = 0.0
        row["dest_amount_vs_avg"] = amount
        row["dest_amount_vs_max"] = amount

    # 4. Re-score
    X = row_to_matrix(row)
    p_xgb_raw = float(S.model.predict_proba(X)[0, 1])
    if S.calibrator is not None:
        try:
            p_xgb = float(S.calibrator.predict([p_xgb_raw])[0])
            p_xgb = max(0.0, min(1.0, p_xgb))
        except Exception:
            p_xgb = p_xgb_raw
    else:
        p_xgb = p_xgb_raw

    gnn_raw = txn.get("gnn_probability")
    p_gnn = float(gnn_raw) if gnn_raw is not None else None
    final = (
        (1.0 - (1.0 - p_xgb) * (1.0 - p_gnn))
        if p_gnn is not None
        else p_xgb
    )

    baseline = float(txn.get("fraud_probability", 0.0))
    baseline_decision = txn.get("decision", "ALLOW")
    cf_decision = "BLOCK" if final >= S.threshold else "ALLOW"

    return {
        "txn_id": body.txn_id,
        "baseline_probability": round(baseline, 6),
        "baseline_decision": baseline_decision,
        "counterfactual_probability": round(final, 6),
        "counterfactual_xgb": round(p_xgb, 6),
        "counterfactual_gnn": round(p_gnn, 6) if p_gnn is not None else None,
        "counterfactual_decision": cf_decision,
        "delta": round(final - baseline, 6),
        "would_change_decision": cf_decision != baseline_decision,
        "threshold": S.threshold,
        "baseline_features": {
            "amount": float(base_row["amount"]),
            "orig_count_24h": int(base_row.get("orig_count_24h", 0) or 0),
            "orig_prior_avg_amount": float(
                base_row.get("orig_prior_avg_amount", 0) or 0
            ),
            "dest_has_history": int(base_row.get("dest_count_24h", 0) or 0) > 0,
        },
    }

@app.get("/rings")
def rings():
    if S.redis is None:
        raise HTTPException(503, "Redis not ready")
    try:
        cached = S.redis.get(REDIS_RINGS_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    result = {}
    try:
        for k in S.redis.keys(f"{GNM_RING_MEMBERS_PREFIX}*"):
            ring_id = k.replace(GNM_RING_MEMBERS_PREFIX, "")
            raw = S.redis.get(k)
            try:
                result[ring_id] = json.loads(raw) if raw else []
            except Exception:
                result[ring_id] = []
    except Exception as e:
        raise HTTPException(503, f"Redis error: {e}")
    payload = {"ring_count": len(result), "rings": result}
    try:
        S.redis.set(REDIS_RINGS_CACHE_KEY, json.dumps(payload), ex=REDIS_RINGS_CACHE_TTL)
    except Exception:
        pass
    return payload


@app.get("/txn/{txn_id}")
def txn_by_id(txn_id: str):
    try:
        cached = S.redis.get(f"{REDIS_TXN_PREFIX}{txn_id}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    conn = sqlite3.connect(CASES_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM cases WHERE txn_id = ?", (txn_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(
            404,
            f"txn {txn_id} not in Redis (TTL expired or never scored) "
            f"and not in cases DB (below review threshold).",
        )
    return dict(row)


@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await manager.connect(ws)
    try:
        try:
            ids = S.redis.zrevrange(REDIS_RECENT_ZSET, 0, 49)
            for tid in ids:
                raw = S.redis.get(f"{REDIS_TXN_PREFIX}{tid}")
                if raw:
                    await ws.send_json(json.loads(raw))
        except Exception:
            pass
        while True:
            try:
                await ws.receive_text()
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)


@app.get("/case/{txn_id}")
def case_by_id(txn_id: str):
    conn = sqlite3.connect(CASES_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM cases WHERE txn_id = ?", (txn_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(
            404,
            f"Case {txn_id} not persisted. Only BLOCK or high-risk ALLOW "
            f"(score >= threshold * 0.5) are persisted. If this txn was "
            f"scored but not persisted, it's a normal ALLOW below cutoff.",
        )
    return dict(row)


@app.post("/feedback", dependencies=[Depends(require_api_key)])
def feedback(body: Feedback):
    if body.label not in ("confirmed_fraud", "false_positive", "needs_review"):
        raise HTTPException(
            400, "label must be confirmed_fraud | false_positive | needs_review"
        )
    conn = sqlite3.connect(CASES_DB, check_same_thread=False)
    try:
        cur = conn.execute(
            "SELECT txn_id FROM cases WHERE txn_id = ?", (body.txn_id,)
        )
        if cur.fetchone() is None:
            raise HTTPException(404, f"Case {body.txn_id} not persisted.")
        conn.execute(
            """
            UPDATE cases SET label = ?, label_by = ?, label_at = ?, notes = ?
            WHERE txn_id = ?
            """,
            (
                body.label, body.label_by,
                datetime.now(timezone.utc).isoformat(),
                body.notes, body.txn_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    log.info(f"Feedback recorded: {body.txn_id} -> {body.label}")
    return {"status": "ok", "txn_id": body.txn_id, "label": body.label}

@app.post("/simulate/attack")
def simulate_attack():
    """Inject a synthetic fraud ring into the live stream.

    Generates 5 fresh accounts sharing one device and one card, then pushes
    5 coordinated CASH_OUT transactions through Kafka. The scoring pipeline
    picks them up automatically.

    To make the demo honest without retraining the GNN, we pre-populate
    Redis with GNN=0.99 and ring metadata for these accounts. This mirrors
    exactly what the trained model would output if it had been fitted on a
    graph containing these accounts â€” the decision path (soft-OR blend,
    threshold, persist-case) is identical.

    Side effects:
      * Redis gains 5 GNM_SCORE_PREFIX keys at 0.99
      * Redis gains 1 GNM_RING_MEMBERS_PREFIX key with the 5 account IDs
      * Redis rings cache is invalidated so /rings picks up the new ring
      * 5 messages on TOPIC_RAW (picked up by consume_loop, then scored)
    """
    import uuid
    ts = int(time.time())
    uid = uuid.uuid4().hex[:6]
    ring_id = f"ring_attack_{ts}_{uid}"
    device_id = f"dev_attack_{ts}_{uid}"
    card_id = f"card_attack_{ts}_{uid}"
    dest = f"C_ATK_DEST_{ts}"
    accounts = [f"C_ATK_{i:02d}_{uid}" for i in range(1, 6)]

    if S.redis is None:
        raise HTTPException(503, "Redis not ready")
    if S.kafka_producer is None:
        raise HTTPException(503, "Kafka producer not ready")

    # 1. Pre-populate Redis so GNN lookup succeeds on first score
    try:
        for acc in accounts:
            S.redis.set(f"{GNM_SCORE_PREFIX}{acc}", "0.99")
            S.redis.set(f"{GNM_RING_ID_PREFIX}{acc}", ring_id)
            S.redis.set(f"{GNM_DEVICE_PREFIX}{acc}", device_id)
            S.redis.set(f"{GNM_CARD_PREFIX}{acc}", card_id)
        S.redis.set(
            f"{GNM_RING_MEMBERS_PREFIX}{ring_id}",
            json.dumps(accounts),
        )
        # Invalidate caches that reference stale ring/account state
        S.redis.delete(REDIS_RINGS_CACHE_KEY)
        S.redis.delete("discovery:acc_maps:v1")     # force re-read of parquet + Redis delta
        S.redis.delete("discovery:result:v1")
        # Also drop any cached replay timelines so new ring gets fresh events
        try:
            cur = 0
            while True:
                cur, ks = S.redis.scan(cursor=cur, match="replay:*", count=1000)
                if ks:
                    S.redis.delete(*ks)
                if cur == 0:
                    break
        except Exception:
            pass
    except Exception as e:
        log.exception("attack: Redis prepopulate failed")
        raise HTTPException(500, f"Redis prepopulate failed: {e}")

    # 2. Push 5 coordinated txns to Kafka
    step = int(time.time()) % 743  # within PaySim step range
    pushed = 0
    try:
        for i, acc in enumerate(accounts):
            txn = {
                "txn_id": f"attack_{ts}_{uid}_{i}",
                "step": step,
                "type": "CASH_OUT",
                "amount": 50000.0,
                "nameOrig": acc,
                "oldbalanceOrg": 50000.0,
                "newbalanceOrig": 0.0,       # full drain â€” the ring signature
                "nameDest": dest,
                "oldbalanceDest": 0.0,
                "newbalanceDest": 50000.0,
                "_truth_isFraud": 1,         # simulated fraud
            }
            S.kafka_producer.send(TOPIC_RAW, txn)
            pushed += 1
        S.kafka_producer.flush(timeout=5)
    except Exception as e:
        log.exception("attack: Kafka push failed")
        raise HTTPException(500, f"Kafka push failed: {e}")

    log.info(
        f"Simulated fraud ring attack: {ring_id} "
        f"({pushed} txns across {len(accounts)} accounts, "
        f"shared device {device_id})"
    )

    return {
        "status": "launched",
        "ring_id": ring_id,
        "device_id": device_id,
        "card_id": card_id,
        "destination": dest,
        "accounts": accounts,
        "txns_pushed": pushed,
        "hint": (
            "Watch Live Alerts â€” 5 BLOCKs will appear within 1â€“3 seconds. "
            "Then open Graph Explorer to see the new ring cluster."
        ),
    }

@app.get("/discovered-rings")
def discovered_rings(force: bool = False):
    """Unsupervised discovery: clusters of accounts sharing device/card
    infrastructure, cross-referenced against known ring labels.

    Cached in Redis for 1 hour. Pass ?force=true to recompute.
    First call takes ~10-20s (parquet read + Redis SCAN); subsequent
    calls are instant.
    """
    cache_key = "discovery:result:v1"
    if not force:
        try:
            cached = S.redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    cutoff_path = PROJECT_ROOT / "data" / "processed" / "warmup_cutoff.txt"
    parquet_path = PROJECT_ROOT / "data" / "processed" / "features_with_rings.parquet"
    if not cutoff_path.exists() or not parquet_path.exists():
        raise HTTPException(503, "Discovery prerequisites missing (parquet or cutoff)")

    cutoff = int(cutoff_path.read_text().strip())
    try:
        result = discover_rings(S.redis, parquet_path, cutoff)
        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        S.redis.setex(cache_key, 12 * 3600, json.dumps(result))
        return result
    except Exception as e:
        log.exception("discovery failed")
        raise HTTPException(500, f"Discovery failed: {e}")


@app.get("/replay/{ring_id}")
def replay_ring(ring_id: str):
    """Return the timeline of events for a ring (attack or original).
    Cached in Redis for 1h."""
    cache_key = f"replay:{ring_id}"
    try:
        cached = S.redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    cutoff_path = PROJECT_ROOT / "data" / "processed" / "warmup_cutoff.txt"
    parquet_path = PROJECT_ROOT / "data" / "processed" / "features_with_rings.parquet"
    if not cutoff_path.exists() or not parquet_path.exists():
        raise HTTPException(503, "Replay prerequisites missing (parquet or cutoff)")

    cutoff = int(cutoff_path.read_text().strip())
    try:
        result = get_ring_replay(S.redis, ring_id, parquet_path, cutoff)
    except Exception as e:
        log.exception("replay failed")
        raise HTTPException(500, f"Replay failed: {e}")

    if result is None:
        raise HTTPException(404, f"Ring {ring_id} not found (no member list in Redis)")

    try:
        S.redis.setex(cache_key, 3600, json.dumps(result))
    except Exception:
        pass
    return result


@app.get("/models")

@app.get("/models")

@app.get("/models")
def models():
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.tracking.MlflowClient()
    results = []
    for exp_name in (EXPERIMENT, EXPERIMENT_GNN):
        exp = client.get_experiment_by_name(exp_name)
        if exp is None:
            continue
        runs = client.search_runs(
            experiment_ids=[exp.experiment_id],
            order_by=["start_time DESC"],
            max_results=50,
        )
        for r in runs:
            if r.data.tags.get("artifact_type") == "calibrator":
                continue
            pr_auc = r.data.metrics.get("pr_auc") or r.data.metrics.get("val_pr_auc_final")
            threshold = (
                r.data.metrics.get("best_threshold")
                or r.data.metrics.get("val_best_threshold")
            )
            start = None
            if r.info.start_time:
                start = datetime.fromtimestamp(
                    r.info.start_time / 1000, tz=timezone.utc
                ).isoformat()
            results.append({
                "run_id": r.info.run_id,
                "experiment": exp_name,
                "kind": "xgboost" if exp_name == EXPERIMENT else "gnn",
                "run_name": r.data.tags.get("mlflow.runName", ""),
                "status": r.info.status,
                "start_time": start,
                "pr_auc": float(pr_auc) if pr_auc is not None else None,
                "threshold": float(threshold) if threshold is not None else None,
                "is_current": r.info.run_id == S.model_run_id,
            })
    results.sort(key=lambda x: x["start_time"] or "", reverse=True)
    return {
        "count": len(results),
        "runs": results,
        "current_run_id": S.model_run_id,
    }


@app.get("/health/deep")
def health_deep():
    uptime = round(time.time() - S.started_at, 1)

    kafka_lag = {}
    if S.kafka_consumer is not None:
        try:
            parts = S.kafka_consumer.assignment()
            if parts:
                end_offsets = S.kafka_consumer.end_offsets(parts)
                for p in parts:
                    try:
                        pos = S.kafka_consumer.position(p)
                        lag = end_offsets.get(p, 0) - (pos or 0)
                        kafka_lag[f"{p.topic}-{p.partition}"] = int(lag)
                    except Exception as e:
                        kafka_lag[f"{p.topic}-{p.partition}"] = f"err: {e}"
        except Exception as e:
            kafka_lag = {"error": str(e)}

    redis_ms = None
    if S.redis is not None:
        try:
            t0 = time.perf_counter()
            S.redis.ping()
            redis_ms = round((time.perf_counter() - t0) * 1000, 3)
        except Exception:
            redis_ms = -1

    try:
        recent_size = S.redis.zcard(REDIS_RECENT_ZSET)
        fb_size = S.redis.llen(REDIS_SAMPLES_LIST)
    except Exception:
        recent_size = 0
        fb_size = 0

    return {
        "uptime_seconds": uptime,
        "model_run_id": S.model_run_id,
        "threshold": S.threshold,
        "threshold_raw": S.threshold_raw,
        "calibrated": S.calibrator is not None,
        "kafka_lag": kafka_lag,
        "kafka_lag_total": sum(v for v in kafka_lag.values() if isinstance(v, int)),
        "redis_ping_ms": redis_ms,
        "ws_clients": len(manager.active),
        "recent_size": recent_size,
        "feature_buffer_size": fb_size,
        "counters": _read_counters(),
        "circuit_breakers": {
            "redis": redis_breaker.status(),
            "feast": feast_breaker.status(),
        },
        "auth_enabled": bool(API_KEYS),
        "rate_limit_per_sec": RATE_LIMIT_PER_SEC,
    }
