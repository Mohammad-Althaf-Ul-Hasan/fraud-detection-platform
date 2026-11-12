"""Prometheus instrumentation for the fraud scoring service.

All metric definitions live here. The scoring service imports helper
functions (record_prediction, record_kafka_consumed, ...) that wrap
the underlying instruments, so the calling code stays readable.

Metric naming follows Prometheus conventions:
  * *_total    → Counter (monotonically increasing)
  * *_seconds  → Histogram (observations in seconds)
  * *          → Gauge (arbitrary value)

For /metrics endpoint, use prometheus_client.make_asgi_app() mounted
in scoring_service.py. Do not re-export generate_latest here.
"""
from prometheus_client import Counter, Gauge, Histogram


# ---------- Prediction metrics ----------------------------------------------

PREDICTIONS_TOTAL = Counter(
    "fraud_predictions_total",
    "Total predictions scored.",
    ["decision", "model_version"],
)

PREDICTION_LATENCY = Histogram(
    "fraud_prediction_latency_seconds",
    "End-to-end scoring latency (seconds).",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

FRAUD_PROBABILITY = Histogram(
    "fraud_probability",
    "Distribution of final fraud probability scores.",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.99, 1.0],
)

GNN_HITS = Counter(
    "fraud_gnn_hits_total",
    "Predictions where the GNN score was available (ring member or cached embedding).",
)

GNN_MISSES = Counter(
    "fraud_gnn_misses_total",
    "Predictions where the GNN score was unavailable (cold-start account).",
)


# ---------- Kafka / consumer metrics ----------------------------------------

KAFKA_CONSUMED = Counter(
    "fraud_kafka_consumed_total",
    "Total Kafka messages consumed.",
)

KAFKA_DUPLICATES = Counter(
    "fraud_kafka_duplicates_total",
    "Kafka messages skipped due to idempotency (already scored).",
)


# ---------- Case persistence ------------------------------------------------

CASES_PERSISTED = Counter(
    "fraud_cases_persisted_total",
    "Cases persisted to SQLite (BLOCK or high-risk ALLOW).",
    ["decision", "is_high_risk"],
)


# ---------- Model metadata --------------------------------------------------

MODEL_INFO = Gauge(
    "fraud_model_info",
    "Current model metadata (always 1; labels carry the values).",
    ["run_id", "calibrated"],
)

DRIFT_SHARE = Gauge(
    "fraud_drift_share",
    "Latest Evidently drift share (0-1).",
)


# ---------- Convenience wrappers --------------------------------------------

def record_prediction(decision: str, latency_ms: float,
                      fraud_probability: float, gnn_probability,
                      model_run_id: str) -> None:
    """Record all per-prediction metrics in one call.

    Called from score_one() so it covers both /predict and the consumer path.
    """
    run_short = (model_run_id or "unknown")[:8]
    PREDICTIONS_TOTAL.labels(decision=decision, model_version=run_short).inc()
    PREDICTION_LATENCY.observe(max(latency_ms, 0.0) / 1000.0)
    FRAUD_PROBABILITY.observe(fraud_probability)
    if gnn_probability is not None:
        GNN_HITS.inc()
    else:
        GNN_MISSES.inc()


def record_kafka_consumed() -> None:
    KAFKA_CONSUMED.inc()


def record_kafka_duplicate() -> None:
    KAFKA_DUPLICATES.inc()


def record_case_persisted(decision: str, is_high_risk: int) -> None:
    CASES_PERSISTED.labels(
        decision=decision,
        is_high_risk="yes" if is_high_risk else "no",
    ).inc()


def set_model_info(run_id: str, calibrated: bool) -> None:
    MODEL_INFO.labels(
        run_id=(run_id or "unknown")[:12],
        calibrated="yes" if calibrated else "no",
    ).set(1)


def set_drift_share(share: float) -> None:
    DRIFT_SHARE.set(max(0.0, min(1.0, share)))