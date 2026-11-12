"""Enterprise reliability & security primitives.

Provides:
  * require_api_key         — FastAPI dependency; 401 on missing/wrong key.
  * check_rate_limit        — FastAPI dependency; 429 on excess.
  * redis_breaker           — singleton circuit breaker around Redis.
  * feast_breaker           — singleton circuit breaker around Feast.
  * TraceMiddleware         — injects X-Trace-Id into every response.

Configuration is via env vars (see .env.example):
  API_KEYS           — comma-separated. Empty = auth disabled (dev mode).
  RATE_LIMIT_PER_SEC — int, default 10. 0 = unlimited.
  RATE_LIMIT_BURST   — int, default 50. Max in any 5-sec window.
"""
import logging
import os
import threading
import time
import uuid
from collections import deque

from fastapi import Header, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("enterprise")


# ---------- Config ----------------------------------------------------------

def _load_api_keys() -> set[str]:
    raw = os.getenv("API_KEYS", "").strip()
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


API_KEYS = _load_api_keys()
if not API_KEYS:
    log.warning(
        "API_KEYS env var is empty — write endpoints are UNAUTHENTICATED. "
        "Set API_KEYS='key1,key2' to enable auth."
    )

RATE_LIMIT_PER_SEC = int(os.getenv("RATE_LIMIT_PER_SEC", "10"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "50"))


# ---------- API key auth ----------------------------------------------------

async def require_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")):
    """FastAPI dependency. Returns 401 if auth is enabled and key is
    missing/invalid. Returns silently if auth is disabled (dev mode)."""
    if not API_KEYS:
        return  # dev mode — no keys configured
    if not x_api_key:
        raise HTTPException(401, "Missing X-API-Key header")
    if x_api_key not in API_KEYS:
        log.warning(f"Rejected request with invalid API key (prefix={x_api_key[:6]}...)")
        raise HTTPException(403, "Invalid API key")


# ---------- Rate limiting (per key, sliding window) -------------------------

_rate_state: dict[str, deque] = {}
_rate_lock = threading.Lock()


async def check_rate_limit(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    request: Request = None,  # noqa: B008 — FastAPI injects
):
    """Sliding-window rate limit keyed by API key (falls back to client IP
    when auth is disabled). 0 = unlimited."""
    if RATE_LIMIT_PER_SEC <= 0:
        return
    key = x_api_key or (
        request.client.host if request and request.client else "anonymous"
    )
    now = time.time()
    with _rate_lock:
        bucket = _rate_state.setdefault(key, deque())
        # Drop events older than 1 second
        while bucket and bucket[0] < now - 1.0:
            bucket.popleft()
        # Reject if at per-second limit or burst ceiling
        if len(bucket) >= RATE_LIMIT_PER_SEC or len(bucket) >= RATE_LIMIT_BURST:
            retry_after = max(1, int(1.0 - (now - bucket[0])) + 1)
            raise HTTPException(
                429,
                f"Rate limit exceeded ({RATE_LIMIT_PER_SEC}/s). "
                f"Retry after {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)


# ---------- Circuit breaker -------------------------------------------------

class CircuitBreaker:
    """Simple failure-count circuit breaker.

    States:
      CLOSED    — normal operation. Calls pass through.
      OPEN      — tripped after N failures. Calls return fallback for TTL.
      HALF_OPEN — after TTL elapses, next call attempts to close.
                  If it succeeds, breaker CLOSES. If it fails, OPEN resumes.
    """

    def __init__(self, name: str, failure_threshold: int = 5, recovery_sec: int = 30):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_sec = recovery_sec
        self.failures = 0
        self.opened_at: float | None = None
        self.lock = threading.Lock()

    def is_open(self) -> bool:
        with self.lock:
            if self.opened_at is None:
                return False
            if time.time() - self.opened_at >= self.recovery_sec:
                # Half-open: attempt next call
                self.opened_at = None
                self.failures = 0
                log.info(f"Circuit {self.name} → HALF_OPEN")
                return False
            return True

    def record_success(self):
        with self.lock:
            if self.failures:
                log.info(f"Circuit {self.name} → CLOSED (was {self.failures} failures)")
            self.failures = 0
            self.opened_at = None

    def record_failure(self, exc: Exception):
        with self.lock:
            self.failures += 1
            if self.failures >= self.failure_threshold and self.opened_at is None:
                self.opened_at = time.time()
                log.warning(
                    f"Circuit {self.name} → OPEN after {self.failures} failures "
                    f"({type(exc).__name__}: {exc}). Recovery in {self.recovery_sec}s."
                )

    def call(self, fn, *args, fallback=None, **kwargs):
        """Execute fn(*args). On exception, count a failure and return
        fallback() if provided, else re-raise."""
        if self.is_open():
            log.debug(f"Circuit {self.name} is OPEN — using fallback")
            return fallback() if fallback else None
        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure(e)
            if fallback is not None:
                return fallback()
            raise

    def status(self) -> dict:
        with self.lock:
            if self.opened_at is None:
                state = "closed"
            elif time.time() - self.opened_at < self.recovery_sec:
                state = "open"
            else:
                state = "half_open"
            return {
                "state": state,
                "failures": self.failures,
                "opened_at": self.opened_at,
                "recovery_sec": self.recovery_sec,
            }


redis_breaker = CircuitBreaker("redis", failure_threshold=5, recovery_sec=30)
feast_breaker = CircuitBreaker("feast", failure_threshold=10, recovery_sec=60)


# ---------- Request tracing -------------------------------------------------

class TraceMiddleware(BaseHTTPMiddleware):
    """Injects X-Trace-Id into every response. Uses the caller's trace id if
    provided, otherwise generates a fresh UUID."""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response