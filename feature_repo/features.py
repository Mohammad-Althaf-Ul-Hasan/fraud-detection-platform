"""Feast definitions — only ACCOUNT AGGREGATE features live here.
Per-transaction fields (amount, balance errors, type flags) travel in
the request payload at serving time.
"""
from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int64

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PARQUET = str(PROJECT_ROOT / "data" / "processed" / "features.parquet")

# Entity: source account
account = Entity(
    name="account_id",
    join_keys=["nameOrig"],
    description="Source account (nameOrig)",
)

# Batch source (parquet produced by compute_features.py)
account_source = FileSource(
    name="account_features_source",
    path=FEATURES_PARQUET,
    timestamp_field="timestamp",
)

# Feature view: what we serve online for an account
account_features = FeatureView(
    name="account_features",
    entities=[account],
    ttl=timedelta(days=30),
    schema=[
        Field(name="orig_count_1h", dtype=Int64),
        Field(name="orig_count_6h", dtype=Int64),
        Field(name="orig_count_24h", dtype=Int64),
        Field(name="orig_sum_1h", dtype=Float32),
        Field(name="orig_sum_6h", dtype=Float32),
        Field(name="orig_sum_24h", dtype=Float32),
        Field(name="orig_prior_avg_amount", dtype=Float32),
        Field(name="orig_prior_max_amount", dtype=Float32),
        Field(name="orig_amount_vs_avg", dtype=Float32),
        Field(name="orig_amount_vs_max", dtype=Float32),
    ],
    source=account_source,
)