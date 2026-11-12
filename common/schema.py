"""Shared schema: single source of truth for FEATURE_COLS and Kafka topics.

IMPORTANT — only pre-transaction fields are listed here. `newbalanceOrig`,
`newbalanceDest`, `balance_error_*`, and `account_drained` are deliberately
excluded: they are the *result* of the transaction and are not available at
decision time. Including them produces a model with PR-AUC ≈ 0.9998 on PaySim
that is useless in production (verified the hard way)."""
FEATURE_COLS = [
    # pre-transaction fields only
    "amount", "oldbalanceOrg", "oldbalanceDest",
    "amount_to_balance_ratio",
    "dest_is_merchant", "hour_of_day",
    "is_transfer", "is_cash_out", "is_payment", "is_cash_in", "is_debit",
    # orig velocity (prior txns only)
    "orig_count_1h", "orig_count_6h", "orig_count_24h",
    "orig_sum_1h", "orig_sum_6h", "orig_sum_24h",
    "orig_prior_avg_amount", "orig_prior_max_amount",
    "orig_amount_vs_avg", "orig_amount_vs_max",
    # dest velocity (prior txns only)
    "dest_count_1h", "dest_count_6h", "dest_count_24h",
    "dest_sum_1h", "dest_sum_6h", "dest_sum_24h",
    "dest_prior_avg_amount", "dest_prior_max_amount",
    "dest_amount_vs_avg", "dest_amount_vs_max",
]

DEFAULT_THRESHOLD = 0.5
TOPIC_RAW = "raw_transactions"
TOPIC_SCORED = "scored_transactions"


ALPHA = 0.85                      
GNM_SCORE_PREFIX          = "gnn:score:"
GNM_RING_ID_PREFIX        = "gnn:ring_id:"
GNM_DEVICE_PREFIX         = "gnn:device:"
GNM_CARD_PREFIX           = "gnn:card:"
GNM_RING_MEMBERS_PREFIX   = "gnn:ring_members:"
REDIS_HOST = "localhost"
REDIS_PORT = 6379


DRIFT_REPORT_DIR            = "reports"
DRIFT_REFERENCE_CACHE       = "reports/reference_features.parquet"
DRIFT_LATEST_JSON           = "reports/latest_drift.json"
DRIFT_RETRAIN_LOG           = "reports/retrain_log.jsonl"
DRIFT_THRESHOLD             = 0.50
DRIFT_RETRAIN_COOLDOWN_HOURS = 24
DRIFT_REFERENCE_SAMPLE_N    = 20000
DRIFT_CURRENT_SAMPLE_N      = 2000
DRIFT_MAX_BUFFER            = 5000

# --- P1: environment-based config ---
import os

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")     # overrides earlier hard-coded value
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))     # overrides earlier hard-coded value

REDIS_RECENT_ZSET      = "alerts:recent"       # ZSET: score=unix_ts, member=txn_id
REDIS_TXN_PREFIX       = "txn:"                # per-txn JSON string, TTL 24h
REDIS_SAMPLES_LIST     = "drift:samples"       # LIST of feature-row JSON strings
REDIS_LATENCIES_LIST   = "latencies:recent"    # LIST of latency-ms strings
REDIS_COUNTERS_HASH    = "stats:counters"      # HASH of int counters
REDIS_IDEM_PREFIX      = "idem:"               # /predict idempotency keys
REDIS_SCORED_PREFIX    = "scored:"             # consumer txn_id dedupe
REDIS_RINGS_CACHE_KEY  = "rings:cache"         # JSON string, TTL 5m

REDIS_TXN_TTL          = 86400       # 24h
REDIS_IDEM_TTL         = 86400       # 24h
REDIS_SCORED_TTL       = 7 * 86400   # 7 days
REDIS_RINGS_CACHE_TTL  = 300         # 5 min

# --- Bundle B: Counterfactual feature cache ---
REDIS_FEATURES_PREFIX = "cf_features:"     # per-txn feature-row cache
REDIS_FEATURES_TTL    = 86400              # 24h — matches REDIS_TXN_TTL