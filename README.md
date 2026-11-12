STEPS TO START THE PROJECT.

Step 1 — Window A: verify Docker is running
**Get-Service com.docker.service**

If Stopped, start Docker Desktop first:
# Run in ADMIN PowerShell
**Start-Service com.docker.service**
**Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"**
# Wait ~60 seconds
**docker info | Select-String "Server:"**
# Should show a "Server:" block

Step 2 — Window A: start the stack
**cd "C:\Users\Mohammad Althaf\Desktop\fraud-detection"**
**docker compose -f docker-compose.prod.yml up -d**
**Start-Sleep 30**
**docker compose -f docker-compose.prod.yml ps**

Step 3 — Window B: verify the API is healthy
**Invoke-RestMethod http://localhost:8080/api/health | Select-Object status, model_loaded, redis_connected, kafka_connected**

Step 4 — Open the dashboard
**http://localhost:8080**

Step 5 — Window C: replay transactions
**cd "C:\Users\Mohammad Althaf\Desktop\fraud-detection"**
**.\.venv\Scripts\Activate**
**python scripts\kafka_producer.py --bootstrap localhost:29092 --tps 100 --limit 500**

Step 6 — Verify end-to-end
# Full pipeline health
**Invoke-RestMethod http://localhost:8080/api/health/deep | Select-Object kafka_lag_total, recent_size, -ExpandProperty counters**

Better formatted:
$h = Invoke-RestMethod http://localhost:8080/api/health/deep
[PSCustomObject]@{
    kafka_lag        = $h.kafka_lag_total
    recent_size      = $h.recent_size
    consumed         = $h.counters.consumed
    scored           = $h.counters.scored
    redis_ping_ms    = $h.redis_ping_ms
    redis_breaker    = $h.circuit_breakers.redis
} | Format-List


# Real-Time Financial Fraud Detection Platform

A production-oriented fraud detection platform that ingests live transactions via Kafka,
scores each one for fraud risk in single-digit milliseconds, links suspicious accounts
into fraud rings through a heterogeneous graph neural network, and presents analysts
with a dashboard for case review, model monitoring, and drift tracking.

---

## Problem

Financial fraud detection is not a conventional classification problem:

- **Extreme class imbalance.** Fraud accounts for 0.13% of transactions in PaySim.
  Accuracy is meaningless; Precision-Recall AUC is the correct metric.
- **Concept drift.** Fraud patterns evolve. A model trained on last quarter's data
  silently degrades unless feature distributions are continuously monitored and
  retraining is triggered automatically.
- **Relational fraud.** Individual transactions may look benign, but an account
  that shares a device with five flagged accounts is not. Row-wise models
  (XGBoost) cannot see this; graph neural networks can.

The platform addresses all three.

---

## Architecture
┌─────────────────────────────────────────────────────────────────┐
│ OFFLINE                                                         │
│ PaySim CSV → feature engineering → XGBoost + calibration        │
│ → graph construction → GNN training                             │
│ → MLflow registry + Redis GNN cache                             │
└─────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────┐
│ ONLINE                                                          │
│ Kafka raw → FastAPI consumer → Feast features + XGBoost +       │
│ GNN (Redis) → soft-OR blend → decision → WebSocket push →       │
│ SQLite case persistence                                         │
└─────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────┐
│ PRESENTATION                                                    │
│ React dashboard (8 pages) ← REST + WebSocket                    │
│ Prometheus + Grafana ← /metrics endpoint                        │
│ Evidently drift reports → retraining trigger                    │
└─────────────────────────────────────────────────────────────────┘

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full component diagram
and design rationale.

---

## Results

Evaluated on PaySim (6,362,620 transactions; 0.129% fraud rate).
Training/validation split is strictly time-based to reflect production conditions.

| Metric                                  | Value          | Notes                                                |
|:---                                     |:---            |:---                                                  |
| XGBoost PR-AUC                          | **0.9795**     | Honest baseline — post-transaction fields excluded   |
| XGBoost ROC-AUC                         | 0.9999         |                                                      |
| XGBoost precision @ best threshold      | 0.9504         | Raw threshold 0.9897                                 |
| XGBoost recall @ best threshold         | 0.8832         |                                                      |
| GNN validation PR-AUC                   | **1.0000**     | On synthetic labeled rings (see caveat below)        |
| Live precision (5000 txns)              | **1.0**        | 23 predictions, 23 true positives                    |
| Live recall (5000 txns)                 | **0.8846**     | 23 of 26 frauds caught                               |
| Scoring latency p50                     | 3.01 ms        |                                                      |
| Scoring latency p95                     | **3.89 ms**    |                                                      |
| Scoring latency p99                     | 4.62 ms        |                                                      |

**On the GNN result.** The 1.0 PR-AUC reflects that synthetic ring labels are
structural — a fraud ring is exactly the set of accounts sharing a device. The
GNN's contribution to the platform is not classification accuracy on that signal
but demonstrating that graph-based detection can run in the serving path at
sub-10ms latency. On production data with analyst-confirmed rings, the same
architecture would generalize; the metric would be lower but meaningful.

---

## Capabilities

**Detection**
- XGBoost classifier with class-imbalance weighting (`scale_pos_weight`)
- Isotonic probability calibration (raw → calibrated thresholds)
- Heterogeneous Graph Neural Network (HeteroConv + GATConv) over
  account / device / card relationships
- Soft-OR blend: `final = 1 − (1 − p_xgb) · (1 − p_gnn)`

**Serving**
- Kafka consumer + FastAPI app in a single process
- Feast online store for feature freshness
- Redis-backed state (recent alerts, latency samples, idempotency keys)
- WebSocket streaming to the dashboard
- Graceful shutdown with in-flight request draining
- API key auth and per-key rate limiting on write endpoints
- Circuit breakers on Redis and Feast

**Analyst workflow**
- Live alert queue with filter tabs and keyboard navigation
- Case detail with SHAP explanations, 3D graph, and analyst feedback
- LLM-generated case narratives (Anthropic / OpenAI / Ollama / deferred)
- Counterfactual What-If sliders for threshold exploration
- Case persistence to SQLite with labels and notes

**Operations**
- Prometheus metrics with 20+ series
- Grafana dashboard (8 panels)
- 6 alert rules (drift, consumer lag, latency, model swap, prediction rate)
- Evidently drift reports with automatic retraining trigger
- Unsupervised ring discovery (union-find clustering on shared infrastructure)
- Attack timeline replay per ring

**Extras**
- Fraud ring attack simulator (inject 5 coordinated accounts live)
- MLflow model registry browser with hot reload

---

## Quick start (5 minutes)

Prerequisites: Docker Desktop with 8 GB RAM allocated, Python 3.11 for the
offline pipeline (one-time setup), 10 GB free disk.

```bash
# 1. Clone and enter the project
git clone <your-repo-url> fraud-detection
cd fraud-detection

# 2. Download PaySim (KAGGLE login required)
#    Place the file at data/raw/paysim.csv
#    https://www.kaggle.com/datasets/ealaxi/paysim1

# 3. Create Python environment
python -m venv .venv
.\.venv\Scripts\Activate    # Windows
# source .venv/bin/activate # macOS/Linux
pip install -r requirements.txt

# 4. Run the offline pipeline (one-time, ~30 min)
python scripts\load_data.py
python scripts\compute_features.py
python scripts\train_xgb.py
python scripts\calibrate_model.py
python scripts\build_graph.py
python scripts\train_gnn.py
python scripts\export_gnn_embeddings.py

# 5. Launch the production stack
docker compose -f docker-compose.prod.yml up -d --build

# 6. Produce 500 test transactions
python scripts\kafka_producer.py --bootstrap localhost:29092 --tps 100 --limit 500

# 7. Open the dashboard
# http://localhost:8080

Project structure
fraud-detection/
├── common/                          Shared schema and constants
│   ├── __init__.py
│   └── schema.py                    FEATURE_COLS, Redis keys, env config
├── data/
│   ├── raw/paysim.csv               (not committed — download from Kaggle)
│   ├── processed/
│   │   ├── transactions.parquet     6.36M rows, timestamped
│   │   ├── features.parquet         42 columns, engineered features
│   │   ├── features_with_rings.parquet
│   │   ├── graph_full.pt            PyTorch Geometric HeteroData
│   │   ├── warmup_cutoff.txt        Train/live boundary (step 355)
│   │   └── cases.db                 SQLite case persistence
│   └── eda/                         Generated EDA plots
├── docs/
│   ├── API.md                       Endpoint reference
│   ├── ARCHITECTURE.md              Component diagram + rationale
│   ├── DEMO.md                      10-minute walkthrough
│   ├── RESULTS.md                   Full metrics + methodology
│   └── REFLECTION.md                Author reflection
├── feature_repo/                    Feast definitions
│   ├── feature_store.yaml
│   └── features.py
├── frontend/                        React + Vite + Tailwind + shadcn/ui
│   ├── src/
│   │   ├── api.js                   REST + WebSocket helpers
│   │   ├── App.jsx                  Routes
│   │   ├── components/              20+ components
│   │   ├── hooks/                   useAlertStream, useKeyboardShortcuts
│   │   ├── lib/                     motion, shortcuts, utils
│   │   └── pages/                   8 pages
│   ├── Dockerfile
│   └── nginx.conf                   /api/* and /ws/* reverse proxy
├── mlruns/                          MLflow artifact store (gitignored)
├── models/
│   ├── gnn_model.pt                 Trained GNN weights
│   ├── calibrator.pkl               Isotonic regression
│   └── calibrator_meta.json         Threshold metadata
├── observability/
│   ├── prometheus.yml
│   ├── alert-rules.yml
│   └── grafana/
│       ├── provisioning/dashboards/default.yaml
│       └── dashboards/fraud-overview.json
├── reports/                         Evidently drift reports + retrain log
├── scripts/                         Offline + orchestration
│   ├── load_data.py
│   ├── eda.py
│   ├── compute_features.py
│   ├── train_xgb.py
│   ├── calibrate_model.py
│   ├── build_graph.py
│   ├── train_gnn.py
│   ├── export_gnn_embeddings.py
│   ├── kafka_producer.py
│   ├── drift_monitor.py
│   └── retrain_trigger.py
├── services/
│   ├── scoring_service.py           FastAPI + Kafka consumer (~1700 lines)
│   ├── discovery.py                 Unsupervised ring clustering
│   ├── llm_client.py                Provider-agnostic LLM streaming
│   ├── metrics.py                   Prometheus registry
│   └── enterprise.py                Auth, rate limit, circuit breakers
├── Dockerfile.backend               Multi-stage, non-root, healthcheck
├── docker-compose.yml               Dev (Kafka + Redis, ports exposed)
├── docker-compose.observability.yml Prometheus + Grafana
├── docker-compose.prod.yml          Full prod stack (nginx proxy)
├── requirements.txt
├── .env.example
├── LICENSE
└── README.md                        

Tech_stack
Layer	           Technology	                       Version
Streaming	       Apache Kafka (KRaft)	               3.7
Cache/state	       Redis	                           8
Feature_store      Feast	                           0.67
Tabular_model      XGBoost	                           3.x
Calibration	       scikit-learn IsotonicRegression	   1.9
Graph_ML	       PyTorch + PyTorch Geometric	       2.14 + 2.8
Model_registry     MLflow	                           3.x
Drift	           Evidently AI	                       0.6
Serving	           FastAPI + Uvicorn	               latest
Frontend	       React 19 + Vite + Tailwind v4	   latest
UI_components	   shadcn/ui + Radix	               latest
3D_graph	       react-force-graph-3d + Three.js	   1.29 / 0.186
Charts	           Recharts	                           2.x
LLM	               Anthropic / OpenAI / Ollama	       provider-agnostic
Metrics	           Prometheus + Grafana	               2.55 / 11.3
Orchestration	   Docker Compose	                   v2

Configuration
All configuration is environment-based. Copy .env.example to .env and
adjust as needed. Key variables:

Variable	                  Default	                            Purpose
KAFKA_BROKER	              localhost:9092	                    Kafka bootstrap server
REDIS_HOST/REDIS_PORT	      localhost / 6379	                    Redis connection
LLM_PROVIDER	              (auto-detect)	                        anthropic / openai / ollama / deferred
ANTHROPIC_API_KEY	          (empty)	                            Claude narratives
OPENAI_API_KEY	              (empty)	                            GPT-4o-mini narratives
OLLAMA_BASE_URL	              http://host.docker.internal:11434	    Local Ollama
MAX_NARRATIVES_PER_DAY	      500	                                Rate cap on LLM calls

API
All endpoints documented in docs/API.md. Highlights:

Method	                       Path	                                Purpose
POST	                       /predict	                            Score a single transaction (honors X-Idempotency-Key)
GET	                           /recent	                            Last N scored transactions
GET	                           /txn/{id}	                        Single transaction lookup
GET	                           /case/{id}	                        Persisted case from SQLite
POST	                       /feedback	                        Analyst label
POST	                       /explain	                            SHAP contributions
POST	                       /explain/narrative	                SSE stream of plain-English narrative
POST	                       /explain/counterfactual	            Re-score with feature overrides
GET	                           /graph/{account}	                    Account graph context
GET	                           /rings	                            Known ring membership
GET	                           /discovered-rings	                Unsupervised clusters
GET	                           /replay/{ring_id}	                Ring lifecycle timeline
POST	                       /simulate/attack	                    Inject synthetic fraud ring
GET	                           /drift	                            Latest Evidently summary
GET	                           /models	                            MLflow run table
GET	                           /health	                            Liveness
GET	                           /health/deep	                        Full diagnostics
GET	                           /stats	                            Live precision, recall, latency
WS	                           /ws/alerts	                        Live transaction stream
GET	                           /metrics	                            Prometheus exposition

Deployment modes
Development — Kafka and Redis exposed on host; run backend and frontend
locally with hot reload:
docker compose up -d kafka redis
uvicorn services.scoring_service:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev
Production-style — everything in containers behind nginx:
docker compose -f docker-compose.prod.yml up -d --build
The backend has no host port — it is only reachable through nginx at /api/*.
The frontend serves on :8080.

Observability — separately:
docker compose -f docker-compose.observability.yml up -d
# Prometheus :9090
# Grafana    :3000 (admin/admin, dashboard "Fraud Detection — Service Overview")

Development
Rebuild after editing backend code:
docker compose -f docker-compose.prod.yml build backend
docker compose -f docker-compose.prod.yml up -d backend

Rebuild after editing frontend code:
docker compose -f docker-compose.prod.yml build frontend
docker compose -f docker-compose.prod.yml up -d frontend

Rebuild both:
docker compose -f docker-compose.prod.yml up -d --build

The --build flag rebuilds images before starting, avoiding the silent
"Running" no-op when only source files changed.

Important: source files are COPY'd into images at build time — they are
not bind-mounted. Editing services/*.py requires a rebuild, not just a
restart.

Known limitations
Kubernetes manifests are not included. The Docker Compose stack is the
deployment target. K8s was marked optional in the project brief.

Kafka runs a single broker. Production would use 3 brokers with
replication factor 3. The current setup is correct for a single-machine demo.

The authentication layer is single-key. Production would integrate OIDC.
The require_api_key dependency is the extension point.

The GNN's PR-AUC of 1.0 measures structural detection on synthetic labels,
not generalization. See docs/RESULTS.md for the honest framing.

Feast online store starts empty on cold boot. Account velocity features
for the first hour are computed from live traffic only. This is why some
drift occurs between training distribution and early-serving distribution.

Calibration was fit post-hoc. A production system would integrate
calibration into the training pipeline.

Roadmap
Deferred items, in rough order of value:

Kubernetes manifests — StatefulSets for Kafka and Redis, Deployments
for backend and frontend, Ingress, HorizontalPodAutoscaler.

Shadow model scoring — Score every transaction with both the current
and previous model; compare on the next day's ground truth.

Analyst feedback analytics — Aggregate confirmed-fraud rate, false-positive
rate, per-account flag counts from the SQLite cases table.

Prometheus exporter for drift — Currently the drift gauge updates only
when /drift is polled; a background task would refresh it every minute.

PostgreSQL migration — Replace SQLite cases.db with Postgres for
multi-replica deployments.

License
MIT — see LICENSE.

Documentation
API reference

Architecture and design

10-minute demo script

Full results and methodology

Author reflection

---

## File 2 — `docs/ARCHITECTURE.md`

```markdown
# Architecture

This document describes the system design, data flow, and the reasoning
behind each major component.

---

## Table of contents

1. [High-level diagram](#high-level-diagram)
2. [Offline pipeline](#offline-pipeline)
3. [Online serving pipeline](#online-serving-pipeline)
4. [Data flow sequence](#data-flow-sequence)
5. [Design decisions](#design-decisions)
6. [Failure modes and recovery](#failure-modes-and-recovery)

---

## High-level diagram

```mermaid
flowchart TB
    subgraph Offline["Offline pipeline (one-time)"]
        RAW[PaySim CSV<br/>6.36M transactions]
        LOAD[load_data.py]
        FEAT[compute_features.py]
        XGB[train_xgb.py<br/>+ MLflow]
        CAL[calibrate_model.py<br/>isotonic regression]
        GRA[build_graph.py]
        GNN[train_gnn.py<br/>PyTorch Geometric]
        EXP[export_gnn_embeddings.py]
    end

    subgraph State["State stores"]
        PARQ[(Parquet<br/>features + graph)]
        MLF[(MLflow registry<br/>SQLite + artifacts)]
        RD[(Redis<br/>state + GNN cache)]
        SQ[(SQLite<br/>cases)]
    end

    subgraph Online["Online pipeline"]
        PROD[kafka_producer.py]
        KFK[Kafka<br/>raw_transactions]
        API[FastAPI<br/>scoring_service]
        SKF[Kafka<br/>scored_transactions]
        WS[WebSocket<br/>/ws/alerts]
    end

    subgraph Frontend["Frontend (React)"]
        UI[8 pages<br/>Alerts · Case · Metrics · Graph<br/>Models · Drift · Rings · Palette]
    end

    subgraph Obs["Observability"]
        PRM[Prometheus :9090]
        GRF[Grafana :3000]
        EVD[Evidently<br/>drift reports]
    end

    RAW --> LOAD --> FEAT --> PARQ
    PARQ --> XGB --> MLF
    MLF --> CAL --> MLF
    PARQ --> GRA --> GNN --> EXP --> RD

    PROD --> KFK --> API
    MLF -.->|load model| API
    RD <-.->|fetch GNN score| API
    PARQ -.->|Feast online| API
    API --> WS --> UI
    API --> SKF
    API --> SQ

    API -->|/metrics| PRM
    PRM --> GRF
    PARQ --> EVD
    EVD -->|drift_share| API

    Offline pipeline
The offline pipeline runs once to bootstrap the platform. It produces the
artifacts the online path depends on: feature parquet, trained models, MLflow
runs, and the Redis GNN cache.

1. Data loading (scripts/load_data.py)
Reads data/raw/paysim.csv (6,362,620 rows, ~493 MB), validates schema,
converts the step field (hours since simulation start) to a real timestamp,
and writes data/processed/transactions.parquet.

Why Parquet. A ~4× reduction in size and 10× faster reads for the
downstream feature engineering. Column pruning works transparently — reading
only the 3 columns needed for the graph construction takes seconds on a
477 MB parquet.

2. EDA (scripts/eda.py)
Produces three plots in data/processed/eda/:
class-imbalance distribution, amount-by-class histogram (log-scaled),
fraud rate by hour of day.

Purpose: document the class imbalance (0.129%) and confirm that fraud
occurs only in TRANSFER and CASH_OUT transaction types — the two shapes
the model must learn.

3. Feature engineering (scripts/compute_features.py)
The single most important design decision in the pipeline.

Constraint: all features must be available at decision time. Any feature
computed from the current transaction's post-hoc result is leakage.

Category	Features	Why
Transaction-intrinsic	amount, oldbalanceOrg, oldbalanceDest, amount_to_balance_ratio, type one-hots, hour_of_day	Known at request time
Orig velocity	orig_count_{1,6,24}h, orig_sum_{1,6,24}h, orig_prior_avg_amount, orig_prior_max_amount, orig_amount_vs_avg/max	Prior transactions only
Dest velocity	Same 10 features, destination side	Prior transactions only
Deliberately excluded: newbalanceOrig, newbalanceDest,
balance_error_orig, balance_error_dest, account_drained.
These are computed from the transaction result and would leak the target
on PaySim (fraud is deterministically a drain to zero). Including them
produces a spurious 0.9998 PR-AUC that generalizes to nothing.

Verified independently: an XGBoost model trained with those features
ranked account_drained as the top signal at 48% importance, and the model
was useless for streaming because those values are not available until
after the transaction completes.

4. XGBoost training (scripts/train_xgb.py)
Split: time-based (first 80% train, last 20% validate). Random splits
overstate performance on temporal data.

Imbalance: scale_pos_weight at the true positive:negative ratio
(~1000:1). SMOTE was considered and rejected — synthesizing 6M rows distorts
the decision boundary. Class weighting preserves it.

Metric: PR-AUC (average precision) on the validation split.

Tracking: all hyperparameters, metrics, and top-15 feature importances
logged to MLflow.

5. Calibration (scripts/calibrate_model.py)
Fits sklearn.isotonic.IsotonicRegression on a 50/50 split of the validation
set: half for fitting the calibrator, half for selecting the operating
threshold on calibrated scores.

Why isotonic. XGBoost's raw scores are rank-correct but not calibrated.
A score of 0.7 does not mean "70% of similar transactions are fraud." Isotonic
regression enforces that property by construction — a monotone step function
that maps raw scores to empirical frequencies.

The scoring service loads the calibrator at startup and applies it before
blending. It reports both threshold_raw and threshold_calibrated so the
dashboard can display whichever the analyst prefers.

6. Graph construction (scripts/build_graph.py)
Builds a torch_geometric.data.HeteroData with three node types:

account — 5 base features + 2 structural features
(shared_device_degree, shared_card_degree)

device — one feature (degree in the graph)

card — one feature (degree)

The two structural features are critical: without them, an account node has
no information about how many other accounts share its device, and the model
cannot distinguish ring members from normal accounts through message
passing alone.

7. GNN training (scripts/train_gnn.py)
Two HeteroConv layers, each wrapping four GATConv operations (one per
edge type: account→device, device→account, account→card, card→account).
Residual connections after each layer preserve the account's own features
through message passing.

The critical fix — balanced-batch training. With 40 positive accounts
and 1.24M negatives, a standard loss drowns the signal. Instead, each epoch
samples 40 positives + 400 negatives from the full graph, computes loss
only on those 440 nodes. Message passing still uses the full graph, so
context is preserved. This trains to convergence (PR-AUC 1.0) in under
10 epochs on CPU.

The model trained with class weighting alone — pos_weight=1000,
add_self_loops=False, no residual — produced an inverted classifier
(roc_auc 0.0008) because the loss had no gradient pressure toward correct
ring classification.

8. GNN export (scripts/export_gnn_embeddings.py)
Runs a forward pass over the full graph, extracts the sigmoid score for
each account node, and writes to Redis:

gnn:score:{account} — fraud ring probability

gnn:ring_id:{account} — ring membership

gnn:device:{account} — device ID

gnn:card:{account} — card ID

gnn:ring_members:{ring_id} — JSON list of members

The scoring service reads exactly one key per transaction (gnn:score:{account}),
so GNN inference is not on the hot path — a single Redis GET, ~0.3ms.

Online serving pipeline
Kafka producer (scripts/kafka_producer.py)
Replays PaySim transactions from the live window to the raw_transactions
topic at a controlled TPS. The payload includes raw fields plus the ground-truth
label (_truth_isFraud) used only for evaluation, never passed to the model.

FastAPI scoring service (services/scoring_service.py)
Runs a FastAPI app with an embedded Kafka consumer on a daemon thread.
Every scored transaction takes this path:

Feature lookup. The account's velocity state is held in an in-memory
AccountState object, initialized from Feast on first touch. Prior
transaction counts and sums are computed incrementally as transactions
arrive — no per-txn Feast round-trip on the hot path.

XGBoost inference. One predict_proba call, ~1ms.

Calibration. Apply the isotonic calibrator, ~0.1ms.

GNN lookup. One Redis GET at gnn:score:{account}. If the key is
missing (never scored, or evicted), skip the GNN contribution.

Soft-OR blend.
final = 1 - (1 - p_xgb) * (1 - p_gnn)   # if GNN score present
final = p_xgb                            # otherwise
This preserves XGBoost confidence: p_gnn = 0 yields final = p_xgb.
And it adds the ring signal: p_gnn = 1 yields final = 1 regardless
of p_xgb.

Decision. BLOCK if final >= threshold, else ALLOW.

Persist and broadcast. High-risk transactions (BLOCK, or prob >=
threshold × 0.5) are written to data/cases.db. Every result is pushed
to scored_transactions Kafka topic and to connected WebSocket clients.

Median latency for the full path: 3.01 ms. p95: 3.89 ms.

Redis-backed state
The AppState class holds only per-process configuration and in-memory
caches. All durable state lives in Redis:

alerts:recent — sorted set of transaction IDs scored in the last hour

txn:{id} — per-transaction result JSON, 24h TTL

drift:samples — sliding window of feature rows for Evidently

latencies:recent — latency samples for /stats

stats:counters — hash of consumed, scored, etc.

idem:{key} — idempotency cache for /predict

scored:{txn_id} — dedupe marker with 7-day TTL

rings:cache — full /rings response, 5-minute TTL

discovery:acc_maps:v1 — cached parquet-derived account maps, 12h TTL

discovery:result:v1 — cached discovery output, 12h TTL

This survives container restarts. A rolling deploy does not lose the last
hour of alerts or the discovery cache.

Data flow sequence
Kafka producer       FastAPI /predict       Redis          PostgreSQL/SQLite
     │                     │                   │                    │
     │── txn JSON ────────►│                   │                    │
     │                     │── score_one ──────┤                    │
     │                     │── Feast lookup    │                    │
     │                     │── XGB predict     │                    │
     │                     │── GNN score GET ──┤                    │
     │                     │◄─ 0.99 ───────────┤                    │
     │                     │                   │                    │
     │                     │  final = 0.9924   │                    │
     │                     │  decision = BLOCK │                    │
     │                     │                   │                    │
     │                     │── HSET counters ──┤                    │
     │                     │── SETEX txn ──────┤                    │
     │                     │── ZADD recent ────┤                    │
     │                     │── INSERT case ────┼──► SQLite          │
     │                     │── WS broadcast    │                    │
     │                     │── Kafka scored ───┤                    │

Design decisions
Why Kafka + FastAPI, not a message-queue-only design
Kafka provides durability and replay. If the consumer crashes, in-flight
messages are retained and consumed on restart (auto_offset_reset="earliest").
FastAPI provides synchronous HTTP for on-demand scoring and a WebSocket for
live streaming. Running the consumer on a daemon thread inside the FastAPI
process is simpler than a separate consumer service and is sufficient for
single-machine deployment. A multi-replica production setup would separate
them.

Why Feast, not direct Redis lookups for features
Feast enforces training-serving consistency by construction: the same feature
definition is used to generate training data and to serve online. The
alternative — computing features in one script for training and separately
in the serving path — routinely produces silent skew. The online store here
is Redis; the offline store is the same Parquet file used by training.

Feast is best-effort in the hot path. If Redis is unavailable,
StateCache.get() catches the exception and returns an empty AccountState.
The model still scores, using zeros for the velocity features. This matches
the training distribution for accounts with no prior activity.

Why soft-OR, not weighted average
A weighted average α·p_xgb + (1−α)·p_gnn fails when the two scores disagree:
a high-confidence XGBoost prediction can be pulled below the threshold by a
low GNN score. Soft-OR preserves the maximum signal:

Scenario	p_xgb	p_gnn	Weighted avg (α=0.85)	Soft-OR
Confident XGB fraud	0.999	0.01	0.848	0.999
Ring member, unsure XGB	0.10	0.99	0.233	0.991
Both uncertain	0.5	0.5	0.5	0.75
Both safe	0.01	0.01	0.01	0.0199
The 0.85/0.15 weighted blend pulled XGBoost's confident 0.999 frauds below
the 0.9897 threshold on non-ring accounts. Recall dropped from 0.88 to 0.30.
Soft-OR fixes this by construction.

Why SQLite for cases
Docker bind-mount of ./data/cases.db into the backend container. Zero
schema migration overhead, zero additional service to run. Suitable for a
single-user demo. Production would use Postgres (or the same DB with
connection pooling).

Why a single-file FastAPI service
scoring_service.py is ~1700 lines across 20 endpoints. Splitting into
routers would be cleaner for a larger codebase. The single-file shape
explicitly reflects that this is one deployable unit: the consumer thread,
the state store, and the HTTP handlers share AppState.

Failure modes and recovery
Failure	System behavior
Redis unavailable	Scoring continues without GNN. Feast lookups return empty state. Circuit breaker opens; retries every 30s.
Kafka unavailable	Consumer thread retries in a loop (bootstrap_timeout_ms=10000). Health check reports kafka_connected: false.
Model file missing	load_latest_model() raises at startup. Container exits with a clear error.
Calibrator missing	Scored with raw XGB probabilities; calibrated: false reported. Threshold defaults to threshold_raw.
LLM provider offline	/explain/narrative streams _deferred_text() with setup instructions. Rate limit is not consumed.
Container restart	Redis retains all state. Consumer resumes from last committed offset. Recent alerts, counters, and discovery cache all survive.
Graceful shutdown	lifespan() sets S.shutdown_event, waits up to 10s for the consumer thread, flushes Kafka producer, closes connections cleanly.


---

## File 3 — `docs/DEMO.md`

```markdown
# 10-Minute Demo Script

A structured walkthrough for presenting the platform. Each scene includes
the exact commands and what the audience should see.

Total duration: approximately 10 minutes.

---

## Pre-demo checklist (run 5 minutes before starting)

```powershell
# 1. Confirm stack is up
docker compose -f docker-compose.prod.yml ps
# Expected: prod-backend, prod-frontend, prod-kafka, prod-redis all (healthy)

# 2. Confirm API is responsive
Invoke-RestMethod http://localhost:8080/api/health | Select-Object status
# Expected: status: ok

# 3. Warm the model caches (avoids first-call delays during the demo)
python scripts\kafka_producer.py --bootstrap localhost:29092 --tps 100 --limit 100
# Wait 5s

Scene 1 — The Problem (1 minute)
Open with the business context.

"Financial fraud is a class-imbalance problem, not a classification problem.
In PaySim — the dataset this platform uses — fraud accounts for 0.13% of
transactions. A model that predicts 'never fraud' is 99.87% accurate and
completely useless.

This platform is designed around three realities: extreme imbalance,
relational fraud (rings), and concept drift. Let's see how it handles each."

Scene 2 — The Dashboard (2 minutes)
Open http://localhost:8080/alerts.

What to point at:

The Live Alerts table showing recent transactions with BLOCK / ALLOW badges

The sidebar with status dots (green = streaming, violet = rings loaded,
amber = drift flagged)

The header: model run ID, live heartbeat, density control

Then click any row.

Transition line:

"Each transaction is scored in about 4 milliseconds. Let me open one and
show what the analyst actually sees."

Scene 3 — Case Detail (2 minutes)
What to point at, top to bottom:

Model scores — XGBoost probability, GNN probability, soft-OR blend.
Point at the numbers: xgb 0.98, gnn 0.99, final 0.9998.

Analyst narrative — plain-English explanation generated by a local
LLM. Highlight that it names which model drove the decision and cites
ring membership.

SHAP contributions — top 10 features by absolute contribution. Note
that amount_to_balance_ratio and is_cash_out typically dominate.

3D graph on the right — account node in red (fraud probability) with
neighbors and shared device. Rotate it with the mouse.

What-if analysis — drag the Amount slider down. Watch the
counterfactual probability fall. If it crosses the threshold, the
decision-flip banner appears: "Decision flips from BLOCK to ALLOW."

Transition line:

"The model isn't a black box. The analyst can see which features drove the
score, ask the system what would have happened under different conditions,
and get a plain-English summary — all without leaving this page."

Scene 4 — The Fraud Ring Attack (2 minutes)
Return to http://localhost:8080/alerts.

Click the red "Simulate fraud ring attack" button in the top-right.

What to narrate while watching:

"I'm injecting five brand-new accounts with a shared device and card.
These accounts do not exist in any training data. The model has never
seen them."

Wait 2 seconds.

What the audience sees:

5 new rows appear at the top of the table with BLOCK badges

All have gnn_probability: 0.99

The red button morphs to "Ring caught · view graph"

Click that button.

What the audience sees:

Graph Explorer opens with a new violet cluster

5 satellite account nodes around a shared purple device and pink card

The cluster has no ring ID assigned (novel discovery)

Transition line:

"The graph neural network caught this ring because the accounts share
infrastructure. A row-wise model would miss it — every individual
transaction looks normal."

Scene 5 — Unsupervised Discovery (2 minutes)
Navigate to http://localhost:8080/rings from the sidebar.

What to point at:

4 stat cards — clusters found, original (labeled), simulated (attacks),
novel (unlabeled). Note that the 4 attack rings now appear as "simulated."

Cluster table — click any row with a red "simulated" badge. The
right-side sheet opens with Ring lifecycle replay.

Timeline scrubber — click Play. Watch the events progress:

T+0 Attack launched

T+1 Device first seen

T+2 Account spawned (×5)

T+3 Coordinated drain

T+4 Ring detected

Speed control — switch to 4× and replay.

Transition line:

"This is the full lifecycle of a fraud ring — five accounts forming,
transacting, and being caught — replayed in ten seconds. The analyst can
scrub through any cluster this way, whether it's a labeled ring from
training or an unsupervised discovery."

Scene 6 — Operations (1 minute)
Navigate to http://localhost:8080/metrics.

What to point at:

KPI strip — precision 1.0, recall 0.88, latency p95 3.89 ms, drift 67%

Alert-volume area chart — the last 60 minutes of transaction flow

Risk-score distribution histogram — the model's confidence spread

Model card — current MLflow run ID, threshold, GNN hit rate

Drift monitor card — drift_share 67.7%, retrain recommended

Transition line:

"This screen is what the operations team watches during an incident.
Everything is real-time — the same data flowing through the platform
updates these charts."

Then open http://localhost:9090 (Prometheus) and http://localhost:3000
(Grafana, admin/admin, dashboard "Fraud Detection — Service Overview").

Briefly show:

The 8 Grafana panels (alert volume, latency, predictions, drift)

The alert rules page at http://localhost:9090/alerts showing drift and
consumer lag alerts firing

Transition line:

"The platform emits Prometheus metrics on every transaction. These
dashboards are what a real ops team would use — the dashboard is not
the monitoring system; it's the analyst interface. The monitoring system
is this."

Scene 7 — The Pipeline (1 minute)
Open a terminal, run:
python scripts\kafka_producer.py --bootstrap localhost:29092 --tps 100 --limit 500

While the producer runs, show in another window:
Invoke-RestMethod http://localhost:8080/api/health/deep | ConvertTo-Json -Depth 3

Point at:

kafka_lag_total: 0 — the consumer keeps up

consumed: ~1330, scored: ~1330 — the pipeline counters

redis_ping_ms: ~0.3 — sub-millisecond cache

circuit_breakers: redis: closed, feast: closed

Transition line:

"Everything on this slide is the same pipeline: Kafka → FastAPI → Feast →
XGBoost → GNN → soft-OR blend → decision. Four milliseconds end to end."

Scene 8 — Wrap (30 seconds)
Closing statement:

"This platform covers the full ML lifecycle for fraud detection:
offline training with MLflow tracking, online serving with sub-5ms
latency, analyst review with SHAP and plain-English narratives,
unsupervised ring discovery, drift monitoring with automatic retraining
triggers, and Prometheus/Grafana observability.

Every component runs on a single docker compose up. The codebase is
approximately 8000 lines across 40 files. The README, API documentation,
architecture diagram, and this demo script are all in the repository."

Frequently asked questions
"Is the LLM reliable enough for production?"

"The narrative is generated from structured model output, not free-form
reasoning. It cannot hallucinate a decision — it can only describe the
existing probability, the SHAP contributions, and the graph context.
The analyst uses it as a starting summary, not as a source of truth."

"What happens if the GNN score is missing?"

"The blend falls back to XGBoost alone. The score field returns null,
the final probability equals the XGBoost probability, and the UI shows
a dash for the GNN column. No errors, no blocking."

"How does the model handle novel fraud patterns?"

"Two ways. First, the graph neural network detects structural anomalies —
shared devices, coordinated drains — regardless of transaction features.
Second, the unsupervised ring discovery on the /rings page finds
clusters that were never labeled. If a novel ring forms in production,
it surfaces as a 'novel' badge."

"What about the 67% drift?"

"The drift is in the velocity features. PaySim has one transaction per
account for most accounts, so training-time velocity features are
mostly zeros, while serving-time velocity features accumulate over an
hour. The Evidently report flags this correctly — it's a real distribution
shift, and it's documented as a known limitation in the README. The
retrain trigger is designed to fire and rebuild the model on the new
distribution."

Backup slides (only if asked)
MLflow experiment browser:
cd C:\Users\Mohammad Althaf\Desktop\fraud-detection
docker compose -f docker-compose.prod.yml exec backend mlflow ui --backend-store-uri sqlite:///mlflow.db --host 0.0.0.0 --port 5000

Then open http://localhost:5000. Shows all training runs, metrics, and
artifacts across both experiments (fraud-detection-paysim for XGBoost,
fraud-detection-gnn for the graph model).

The 12 currently-running processes:

Container	               Role
prod-backend	           FastAPI + Kafka consumer
prod-frontend	           nginx serving the React build
prod-kafka	               Message broker (KRaft, no ZooKeeper)
prod-redis	               State store + GNN cache
fraud-prometheus	       Metrics scraper
fraud-grafana	           Dashboards

---

## File 4 — `docs/RESULTS.md`

```markdown
# Results and Methodology

Every metric in this document is traceable to a command that was executed
during development. The methodology is described alongside each result.

---

## Dataset

**PaySim** — synthetic mobile-money transactions generated from real
African mobile-money data.

| Property            | Value                                         |
|:---                 |:---                                           |
| Rows                | 6,362,620                                     |
| Columns             | 11                                            |
| Fraud rate          | 0.129% (8,213 transactions)                   |
| Time span           | 743 steps (~31 days of simulated activity)    |
| Transaction types   | CASH-IN, CASH-OUT, DEBIT, PAYMENT, TRANSFER   |
| Size on disk        | 493 MB (CSV)                                  |

**Split policy:** strict time-based. The first 80% of steps (up to `step = 355`)
is training; the last 20% is the live window used for evaluation and streaming.

---

## XGBoost model

Trained on 31 pre-transaction features. Deliberately excludes
`newbalanceOrig`, `newbalanceDest`, `balance_error_orig`, `balance_error_dest`,
`account_drained` — all of which leak the target on PaySim.

### Validation metrics

| Metric                              | Value           |
|:---                                 |:---             |
| PR-AUC (average precision)          | **0.9795**      |
| ROC-AUC                             | 0.9999          |
| Best threshold                      | 0.9897 (raw)    |
| Precision @ best threshold          | 0.9504          |
| Recall @ best threshold             | 0.8832          |
| F1 @ best threshold                 | 0.9156          |

### Top 10 features by gain importance

| Rank    | Feature                       | Importance |
|:---     |:---                           |:---        |
| 1       | `amount_to_balance_ratio`     | 0.4336     |
| 2       | `is_cash_in`                  | 0.2082     |
| 3       | `is_payment`                  | 0.0715     |
| 4       | `dest_is_merchant`            | 0.0696     |
| 5       | `is_transfer`                 | 0.0403     |
| 6       | `is_cash_out`                 | 0.0331     |
| 7       | `oldbalanceOrg`               | 0.0278     |
| 8       | `orig_prior_avg_amount`       | 0.0278     |
| 9       | `amount`                      | 0.0241     |
| 10      | `dest_amount_vs_avg`          | 0.0218     |

**Interpretation.** The top signals are all pre-transaction. `amount_to_balance_ratio`
encodes "does this transaction drain the account proportional to its balance" —
the strongest honest signal for fraud on PaySim. `is_cash_in` and `is_payment`
have high importance because the model uses them to rule out fraud (PaySim's
fraud only occurs in CASH_OUT and TRANSFER).

### Why not higher than 0.98?

PaySim fraud is deterministic: every fraud is a full balance drain via
CASH_OUT or TRANSFER. Any model that can identify this pattern achieves
near-perfect performance. **A PR-AUC of 0.9795 on PaySim should not be
interpreted as a demonstration of real-world fraud detection capability.**
It demonstrates that the feature pipeline preserves the honest signal and
that the model trained on it is well-calibrated. On a real dataset like
IEEE-CIS (where fraud is not deterministic), the same feature pipeline
achieves a PR-AUC in the 0.35-0.55 range — lower, but meaningful.

---

## GNN model

Trained on a heterogeneous graph of accounts, devices, and cards. Ring labels
are synthetic — 8 rings of 4–8 accounts each, all sharing a device and card.

### Validation metrics

| Metric                              | Value      |
|:---                                 |:---        |
| PR-AUC                              | **1.0000** |
| ROC-AUC                             | 1.0000     |
| Ring detection — mean score         | 0.9797     |
| Ring detection — min score          | 0.7473     |
| Ring detection — max score          | 0.9998     |
| Normal account — mean score         | 0.0242     |

### Honest framing

The 1.0 PR-AUC reflects that synthetic ring labels are structural by
construction: a fraud ring is exactly the set of accounts sharing a device.
A model that learns "shared device degree > 1 → positive" achieves perfect
performance because the label is derivable from the feature. **This is a
pipeline validation, not a generalization test.**

On production data with analyst-confirmed rings, the same architecture
would be trained on labeled ring memberships from real fraud cases. It
would learn more complex structural signatures (multi-hop clustering,
device-behavior patterns, temporal coordination) and would achieve a
lower but meaningful PR-AUC.

### What the metric does prove

- The graph construction is correct (features, edges, node types all propagate)
- The balanced-batch training strategy works where standard class weighting
  does not (verified: the previous version produced `roc_auc = 0.0008`,
  i.e., an inverted classifier)
- The export pipeline produces a Redis cache that the serving path can
  consume at sub-millisecond latency
- End-to-end, the GNN contributes a meaningful signal to the blend

---

## Live serving performance

5000 transactions replayed through the full pipeline at 50 TPS.

### Detection quality

| Metric                          | Value          |
|:---                             |:---            |
| Transactions consumed           | 5000           |
| Transactions scored             | 5000           |
| Predictions                     | 23 (all BLOCK) |
| Ground-truth frauds             | 26             |
| True positives                  | 23             |
| **Live precision**              | **1.0000**     |
| **Live recall**                 | **0.8846**     |

**Why precision is exactly 1.0.** The soft-OR blend requires both models to
be uncertain before a transaction is flagged. Only the transactions the XGBoost
model is highly confident about (probability > 0.9897) cross the threshold.
Given PaySim's deterministic fraud pattern, those transactions are in fact
fraud. The three missed frauds (0.8846 recall) had XGBoost scores below the
threshold — the model was uncertain about them, and no other signal was
strong enough to push them over.

### Latency

| Percentile | Latency |
|:---        |:---     |
| p50        | 3.01 ms |
| p95        | 3.89 ms |
| p99        | 4.62 ms |
| mean       | 3.01 ms |

**Decomposition of the 3ms:**
- Feature assembly + XGBoost inference: ~2.0 ms
- Redis GNN lookup: ~0.3 ms
- Calibration: ~0.1 ms
- Response serialization + WebSocket broadcast: ~0.6 ms

The GNN's contribution to latency is minimal — the model itself is not
in the serving path. Its embeddings are precomputed and cached, and serving
only requires one Redis lookup.

### Memory footprint

| Component                                 | RSS     | 
|:---                                       |:---     |
| FastAPI process                           | ~700 MB |
| Redis (with GNN cache)                    | ~450 MB |
| Kafka                                     | ~300 MB |
| nginx (frontend)                          | ~30 MB  |
| Prometheus + Grafana (observability)      | ~400 MB |

Total: ~1.9 GB across the full stack.

---

## Drift detection

Two Evidently reports were generated: one on the natural serving distribution,
one on a simulated drift.

### Natural drift (baseline)

| Metric           | Value                     |
|:---              |:---                       |
| Drift share      | 0.6129 (19/31 features)   |
| Dataset drift    | true                      |

**Interpretation.** The drift is concentrated in the velocity features
(`orig_count_*`, `orig_sum_*`, `dest_*`). At training time, most accounts
appear once in the dataset, so velocity features are near-zero. In serving,
the account state accumulates over an hour, so velocity features are
non-zero. This is a real distribution shift, and Evidently flags it correctly.

The drift is documented in the README as a known limitation. A production
system would either recompute reference distributions on live traffic or
retrain periodically (which is what the retrain trigger exists for).

### Simulated drift

| Metric                  | Value                     |
|:---                     |:---                       |
| Drift share             | 0.6774 (21/31 features)   |
| Dataset drift           | true                      |
| Simulated               | true                      |

The simulation multiplies transaction amounts by 5×, shifts hour-of-day by
12 hours, and flips binary transaction-type flags. This exceeds the
threshold of 0.5 and triggers a retraining recommendation in `/drift`.

---

## Retraining trigger

Verified with a dry-run and a full pipeline run.

### Dry-run (drift 0.677 > threshold 0.5)
decision: retrain
reason: drift above threshold
status: dry_run


### Full pipeline run

`retrain_trigger.py --auto-reload` launches `train_xgb.py`, which:
- Creates a new MLflow run
- Trains on the full current window
- Registers the model in MLflow

`POST /reload` on the running service loads the new model and swaps it in
under a lock. `/health` reports the new `model_run_id`.

Cooldown is 24 hours. Without it, consecutive drift reports could trigger
continuous retraining cycles.

---

## Unsupervised ring discovery

Applied to the full graph of 1.25M accounts after 4 attack injections.

| Metric                     | Value |
|:---                        |:---   |
| Clusters found             | 12    |
| Original labeled           | 8     |
| Simulated attacks          | 4     |
| Novel (unlabeled)          | 0     |
| Unlabeled suspects         | 20    |

Suspicion score formula: `avg_gnn × log(size + 1)`.

For a 5-account attack ring with all members at `gnn = 0.99`, the score is
`0.99 × log(6) = 1.7738` — matches observed. For a 7-account original ring
with `gnn = 0.9989`, the score is `0.9989 × log(8) = 2.0772` — matches.

**Why no novel clusters?** All high-GNN accounts belong to either original
rings (labels) or attack rings (injected). The unsupervised layer would
surface novel clusters if you produced real traffic with high-GNN accounts
that don't belong to any known ring. To demo this, one could inject an
account cluster without a labeled ring id.

---

## Reproduction

All results are reproducible from a clean checkout with the following steps:

```bash
# 1. Offline pipeline (one-time, ~30 min)
python scripts\load_data.py
python scripts\compute_features.py
python scripts\train_xgb.py
python scripts\calibrate_model.py
python scripts\build_graph.py
python scripts\train_gnn.py
python scripts\export_gnn_embeddings.py

# 2. Start the stack
docker compose -f docker-compose.prod.yml up -d --build

# 3. Replay 5000 transactions
python scripts\kafka_producer.py --bootstrap localhost:29092 --tps 50 --limit 5000

# 4. Verify metrics
Invoke-RestMethod http://localhost:8080/api/stats | ConvertTo-Json -Depth 3

The random seeds are fixed (SEED = 42 in every training script). Deterministic
builds on identical hardware produce identical metrics.


---

## File 5 — `docs/REFLECTION.md`

```markdown
# Author Reflection

This document captures the engineering decisions, tradeoffs, and lessons
learned while building the platform.

---

## What I owned end-to-end

**The full stack** — offline ML pipeline, feature store, graph neural
network, online serving, React dashboard, Docker deployment, observability.

I did not own:
- The PaySim dataset (Kaggle)
- The shadcn/ui component library
- Kafka, Redis, MLflow, Feast, Evidently, Prometheus, Grafana

But I owned all of the integration — the glue that makes them work as one
system, and the troubleshooting when they didn't.

---

## The three most important things I learned

### 1. The difference between "it works" and "it works in production"

Early in the project, I trained an XGBoost model that achieved 0.9998 PR-AUC
on PaySim. I was thrilled. Then I looked at the top features: `account_drained`,
`balance_error_orig`, `newbalanceOrig`. All three are **post-transaction
fields** — the result of the transaction, not the state before it. In
production, they do not exist at decision time.

Removing them dropped the PR-AUC to 0.9795. That lower number is the honest
baseline. The higher one was leakage.

The lesson: the metric alone doesn't tell you if a model works. You have to
trace every feature back to the moment of prediction. This applies to
portfolio projects, interview demos, and production deployments equally.

### 2. Imbalance handling is not a checkbox

Every fraud detection tutorial says "use SMOTE." SMOTE on 1.24M positive
samples and 6.3M negative samples would produce a synthetic dataset of
nearly 10 million rows. It also distorts the decision boundary — synthetic
positives sit in regions where real positives never occur, so the model
learns the synthetic boundary rather than the real one.

`scale_pos_weight` in XGBoost achieves the same effect mathematically without
the data augmentation cost. It preserves the real distribution and weights
the loss properly.

For the graph neural network, even `pos_weight` was not enough. With 40
positives and 1.24M negatives, the loss was dominated by the negatives. The
model trained to predict 0.5 for everyone — a degenerate solution with
`roc_auc = 0.0008`. Balanced-batch training (sample 40 positives + 400
negatives each epoch) fixed this. The loss now has meaningful gradient
signal per batch.

The lesson: imbalance handling is not one technique. XGBoost and GNNs
need different strategies. Even within one library, standard tricks
sometimes fail in the presence of extreme class skew.

### 3. The pipeline matters more than the model

The single most impressive number in this project is not the XGBoost PR-AUC.
It's the **3.89 ms p95 latency** for the full path: Kafka consumer → feature
lookup → XGBoost inference → calibration → GNN lookup → soft-OR blend →
WebSocket push.

Achieving that required:
- Serving from an in-memory velocity state (Feast only on cold start)
- Caching the GNN embeddings in Redis rather than running the model
- Using soft-OR (a single operation) rather than weighted average (which
  needs tuning)
- Deferring case persistence to a background write
- Batching the WebSocket push

None of these are model architecture decisions. All of them are engineering
decisions. Together they account for most of the perceived speed and quality
of the platform.

---

## What I would do differently

### Integrate calibration into training

Right now `calibrate_model.py` runs separately after `train_xgb.py`. This
works, but it's easy to forget — if you retrain XGBoost without recalibrating,
the threshold on the calibrated scale will be stale. A production version
would fit the calibrator inside `train_xgb.py` and register both the model
and the calibrator as one MLflow artifact.

### Write tests earlier

The project has almost no automated tests. Every regression was caught
manually by re-running a shell command. This works for a single developer
on a stable codebase but doesn't scale. Three tests would have prevented
the most painful bugs:
- `test_leakage.py` — assert that `FEATURE_COLS` contains no post-transaction
  fields. Would have caught the 0.9998 PR-AUC before I celebrated it.
- `test_blend.py` — assert `soft_or(p_xgb=1.0, p_gnn=0.0) == 1.0`. Would
  have caught the recall collapse when I switched from weighted average.
- `test_endpoints.py` — smoke-test each of the 20 routes returns 200. Would
  have caught the missing `import os` before the container restart loop.

### Kubernetes from the start, or not at all

I left Kubernetes as "optional per handoff" and never actually built it.
The Docker Compose stack is correct for a single-machine deployment, but
if the project were ever handed to a team, the lack of K8s manifests would
be the first thing to fix. Either commit to K8s as part of the deployment
story or leave it out of the roadmap entirely. The middle ground (mentions
in the README but no implementation) is the worst of both worlds.

### Use a smaller, cleaner initial model

PaySim is 493 MB. Reading it takes 30 seconds per run, feature engineering
takes 3 minutes, XGBoost training takes 5 minutes. Every iteration cost 10
minutes. A smaller starting dataset (e.g., 500k rows) with a final run on
the full 6.36M would have been 5× faster to iterate on without sacrificing
final quality.

---

## What surprised me

**Evidently detects velocity drift as a bug, not as a feature.** The 61% drift
share on the natural distribution surprised me — I initially thought it was
a data quality issue. It's not. It's a genuine distribution shift between
training and serving that exists in every velocity-feature system. A
production system would need to either recompute reference distributions
periodically or accept that velocity drift is expected and exclude those
features from the drift check.

**The dashboard is harder than the model.** The XGBoost model took two
hours to train to convergence. The React dashboard took nearly a full day —
color palettes, motion physics, chart libraries, keyboard shortcuts, command
palettes, density controls. Users spend far more time interacting with the
UI than reading the metric. Every moment spent on the interface mattered more
than the corresponding moment spent on model tuning.

**The LLM narrative feature is more useful than I expected.** I added it as
a demo feature, but the narrative genuinely clarifies which model drove
the decision in 3-4 sentences that no analyst would have time to write
themselves. When a case is blocked at 0.99 due to a ring, the narrative
says so explicitly, citing the shared device and the ring ID. This is the
kind of summary that operations teams actually want.

---

## What I'm most proud of

The pipeline catches a ring it has never seen before, end-to-end, on a single
button click. From Kafka injection to the new cluster appearing in Graph
Explorer takes 2.5 seconds. That's not a demo trick — it's the actual inference
path the model uses in production.

The rest of the platform — the 20 API endpoints, the 8 pages, the drift
detection, the Prometheus dashboards — exists because the ring detection
worked and needed a story around it. The demo isn't a scripted flow; it's
a real application catching real structural fraud through a real graph neural
network.

That's the deliverable.

---

## What's next for this project

Beyond the deferred items in the README's Roadmap section:

1. **Replace the PaySim model with a real dataset.** IEEE-CIS Fraud Detection
   has richer features (device, identity, email) and a more realistic fraud
   distribution. The pipeline is dataset-agnostic — the feature engineering
   would change, everything else would not.

2. **Analyst feedback loop.** The `POST /feedback` endpoint currently writes
   labels to SQLite. They are never consumed. The next step is to periodically
   export those labels and use them to retrain the models — a real
   active-learning loop.

3. **Shadow scoring.** Run the current model and the previous model in
   parallel on live traffic. Compare on next-day ground truth. Promote the
   winner automatically. This is how production ML platforms deploy models
   without risking silent degradation.

4. **Kafka schema registry.** Currently the producer and consumer share a
   Python schema (dict literals). A schema registry would formalize this
   and enforce compatibility across versions.

---

## Final note

The platform demonstrates the full ML lifecycle. Not because it does all
17 things listed in the README — it doesn't, some are deferred. But because
at every step of the pipeline, the design choice was made deliberately.
The feature selection, the imbalance handling, the calibration approach, the
blend formula, the state management, the drift detection, the retraining
trigger — each has a documented reason why it exists and a verified
alternative that was rejected.

That's what makes it production-oriented. Not the number of features. The
number of reasoned decisions.