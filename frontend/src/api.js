const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`GET ${path} → ${res.status} ${body.slice(0, 120)}`);
  }
  return res.json();
}

const API_KEY = import.meta.env.VITE_API_KEY || "";

async function apiPost(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`POST ${path} → ${res.status} ${text.slice(0, 120)}`);
  }
  return res.json();
}

export const endpoints = {
  health:     ()       => apiGet("/health"),
  deepHealth: ()       => apiGet("/health/deep"),
  stats:      ()       => apiGet("/stats"),
  recent:     (n = 20) => apiGet(`/recent?n=${n}`),
  txn:        (id)     => apiGet(`/txn/${encodeURIComponent(id)}`),
  case:       (id)     => apiGet(`/case/${encodeURIComponent(id)}`),
  graph:      (id)     => apiGet(`/graph/${encodeURIComponent(id)}`),
  rings:      ()       => apiGet("/rings"),
  drift:      ()       => apiGet("/drift"),
  models:     ()       => apiGet("/models"),
  explain:    (txn)    => apiPost("/explain", txn),
  counterfactual: (body) => apiPost("/explain/counterfactual", body),
  simulateAttack: ()     => apiPost("/simulate/attack", {}),
  discoveredRings: (force = false) => apiGet(`/discovered-rings${force ? "?force=true" : ""}`),
  replayRing:  (ringId) => apiGet(`/replay/${encodeURIComponent(ringId)}`),
  feedback:   (body)   => apiPost("/feedback", body),
  reload:     ()       => apiPost("/reload", {}),
};

export const WS_BASE = API_BASE.startsWith("http")
  ? API_BASE.replace(/^http/, "ws")
  : "";