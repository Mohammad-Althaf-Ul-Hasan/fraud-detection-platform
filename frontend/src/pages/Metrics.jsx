import { useEffect, useMemo, useRef, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid,
  ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis,
} from "recharts";
import { toast } from "sonner";
import { endpoints } from "@/api";
import { useAlertStream } from "@/hooks/useAlertStream";
import Sparkline from "@/components/Sparkline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Activity, AlertTriangle, CheckCircle2, Clock, Database,
  RefreshCw, Server, TrendingUp, Zap,
} from "lucide-react";

const HISTORY = 30;   // max stats snapshots kept for sparklines

export default function Metrics() {
  const { connected, alerts } = useAlertStream(500);
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [deep, setDeep] = useState(null);
  const [drift, setDrift] = useState(null);
  const [history, setHistory] = useState([]);   // [{precision, recall, blocked, p95}]
  const [error, setError] = useState(null);
  const [reloading, setReloading] = useState(false);
  const statsRef = useRef(stats);
  statsRef.current = stats;

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const [s, h, d, dp] = await Promise.all([
          endpoints.stats(),
          endpoints.health(),
          endpoints.drift().catch(() => null),
          endpoints.deepHealth().catch(() => null),
        ]);
        if (cancelled) return;
        setStats(s); setHealth(h); setDrift(d); setDeep(dp);
        setError(null);
        setHistory((prev) => {
          const next = [
            ...prev,
            {
              precision: s.live_precision,
              recall: s.live_recall,
              blocked: s.counters.predicted_fraud,
              p95: s.latency_ms.p95,
            },
          ];
          return next.slice(-HISTORY);
        });
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    }
    poll();
    const t = setInterval(poll, 2000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  // 60-minute alert volume buckets from live WS alerts
  const alertVolume = useMemo(() => {
    const now = Date.now();
    const bins = new Array(60).fill(0);
    for (const a of alerts) {
      const ts = a._receivedAt || now;
      const ageMin = Math.floor((now - ts) / 60000);
      if (ageMin >= 0 && ageMin < 60) bins[59 - ageMin] += 1;
    }
    return bins.map((count, i) => ({ minute: i - 59, count }));
  }, [alerts]);

  // Risk-score distribution (10 bins over [0, 1])
  const riskHistogram = useMemo(() => {
    const bins = Array.from({ length: 10 }, (_, i) => ({
      bin: `${(i * 0.1).toFixed(1)}`,
      count: 0,
    }));
    for (const a of alerts) {
      const p = a.fraud_probability ?? 0;
      const idx = Math.min(9, Math.floor(p * 10));
      bins[idx].count += 1;
    }
    return bins;
  }, [alerts]);

  async function handleReload() {
    setReloading(true);
    try {
      const r = await endpoints.reload();
      toast.success(`Model reloaded`, {
        description: `run ${r.current_run_id?.slice(0, 8)} · thr ${r.threshold?.toFixed(4)}`,
      });
    } catch (e) {
      toast.error("Reload failed", { description: e.message });
    } finally {
      setReloading(false);
    }
  }

  if (error) return <div className="p-6 text-red-400">Error: {error}</div>;
  if (!stats) return (
    <div className="p-6 space-y-3">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );

  const precisionSeries = history.map((h) => h.precision ?? 0);
  const recallSeries = history.map((h) => h.recall ?? 0);
  const blockedSeries = history.map((h) => h.blocked ?? 0);
  const p95Series = history.map((h) => h.p95 ?? 0);

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">System Metrics</h1>
          <p className="text-sm text-muted-foreground">
            Live operational dashboard · refreshes every 2 s
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="relative flex h-2 w-2">
            {connected && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${connected ? "bg-emerald-500" : "bg-red-500"}`} />
          </span>
          {connected ? "Live" : "Reconnecting"}
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KPI title="Precision" value={stats.live_precision?.toFixed(3)} series={precisionSeries} stroke="#22c55e" />
        <KPI title="Recall"    value={stats.live_recall?.toFixed(3)}    series={recallSeries}    stroke="#3b82f6" />
        <KPI title="Blocked"   value={stats.counters.predicted_fraud}   series={blockedSeries}   stroke="#ef4444" />
        <KPI title="p95 (ms)"  value={stats.latency_ms.p95?.toFixed(2)} series={p95Series}       stroke="#f59e0b" />
        <KPI title="Drift"     value={drift?.report_exists ? (drift.drift_share * 100).toFixed(0) + "%" : "—"}
             series={[]} stroke="#a855f7" />
      </div>

      {/* Two-column: alert volume + risk histogram */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-sm font-semibold">Alert volume (last 60 min)</h2>
              <p className="text-xs text-muted-foreground">Live events per minute</p>
            </div>
            <Badge variant="outline" className="text-[10px]">{alerts.length} buffered</Badge>
          </div>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={alertVolume}>
                <defs>
                  <linearGradient id="alertGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                <XAxis dataKey="minute" stroke="#94a3b8" tick={{ fontSize: 10 }} interval={9} />
                <YAxis stroke="#94a3b8" tick={{ fontSize: 10 }} />
                <RTooltip
                  contentStyle={{ background: "#1e293b", border: "1px solid #334155", fontSize: 12 }}
                  labelFormatter={(v) => `${-v} min ago`}
                />
                <Area type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={1.5} fill="url(#alertGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-sm font-semibold">Risk score distribution</h2>
              <p className="text-xs text-muted-foreground">Last {alerts.length} events, 10 bins</p>
            </div>
            <Badge variant="outline" className="text-[10px]">
              threshold {stats.threshold?.toFixed(4)}
            </Badge>
          </div>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={riskHistogram}>
                <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                <XAxis dataKey="bin" stroke="#94a3b8" tick={{ fontSize: 10 }} />
                <YAxis stroke="#94a3b8" tick={{ fontSize: 10 }} />
                <RTooltip
                  contentStyle={{ background: "#1e293b", border: "1px solid #334155", fontSize: 12 }}
                  labelFormatter={(v) => `score ${v}–${(parseFloat(v) + 0.1).toFixed(1)}`}
                />
                <Bar dataKey="count" fill="#ef4444" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Two-column: model health + drift */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-4">
          <div className="flex items-start justify-between mb-3">
            <div>
              <h2 className="text-sm font-semibold">Model</h2>
              <p className="text-xs text-muted-foreground">Currently serving</p>
            </div>
            <Button size="sm" variant="outline" onClick={handleReload} disabled={reloading}>
              <RefreshCw className={`h-3 w-3 mr-1.5 ${reloading ? "animate-spin" : ""}`} />
              {reloading ? "Reloading…" : "Reload latest"}
            </Button>
          </div>
          <dl className="grid grid-cols-2 gap-y-2 text-xs">
            <DT k="Run ID" v={health?.model_run_id?.slice(0, 12)} mono />
            <DT k="Threshold" v={health?.threshold?.toFixed(4)} mono />
            <DT k="Blend" v={health?.blend_mode} />
            <DT k="GNN hits" v={stats.counters.gnn_hits} mono />
            <DT k="GNN misses" v={stats.counters.gnn_misses} mono />
            <DT k="Buffer" v={health?.feature_buffer_size} mono />
          </dl>
        </Card>

        <Card className="p-4">
          <div className="flex items-start justify-between mb-3">
            <div>
              <h2 className="text-sm font-semibold">Drift monitor</h2>
              <p className="text-xs text-muted-foreground">Evidently · reference vs live</p>
            </div>
            {drift?.retrain_recommended && (
              <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/30">
                <AlertTriangle className="h-3 w-3 mr-1" /> retrain
              </Badge>
            )}
          </div>
          {drift?.report_exists ? (
            <dl className="grid grid-cols-2 gap-y-2 text-xs">
              <DT k="Drift share" v={`${(drift.drift_share * 100).toFixed(1)}%`} />
              <DT k="Drifted cols" v={`${drift.drifted_columns} / ${drift.total_columns}`} />
              <DT k="Dataset drift" v={drift.dataset_drift ? "yes" : "no"} />
              <DT k="Simulated" v={drift.simulated_drift ? "yes" : "no"} />
              <DT k="Reference" v={`${drift.reference_rows?.toLocaleString() ?? "—"} rows`} />
              <DT k="Current" v={`${drift.current_rows?.toLocaleString() ?? "—"} rows`} />
            </dl>
          ) : (
            <div className="text-xs text-muted-foreground">
              No drift report yet. Run <code className="font-mono">scripts/drift_monitor.py</code>.
            </div>
          )}
        </Card>
      </div>

      {/* System status strip */}
      <Card className="p-4">
        <h2 className="text-sm font-semibold mb-3">System status</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <Status
            icon={Server}
            label="Backend uptime"
            value={deep ? formatUptime(deep.uptime_seconds) : "—"}
            tone="ok"
          />
          <Status
            icon={Database}
            label="Kafka lag"
            value={deep ? `${deep.kafka_lag_total ?? 0} msgs` : "—"}
            tone={deep?.kafka_lag_total > 100 ? "warn" : "ok"}
          />
          <Status
            icon={Zap}
            label="Redis ping"
            value={deep?.redis_ping_ms != null ? `${deep.redis_ping_ms.toFixed(2)} ms` : "—"}
            tone={deep?.redis_ping_ms < 5 ? "ok" : "warn"}
          />
          <Status
            icon={Activity}
            label="WS clients"
            value={deep?.ws_clients ?? "—"}
            tone="ok"
          />
        </div>
      </Card>
    </div>
  );
}

function KPI({ title, value, series, stroke }) {
  return (
    <Card className="p-3">
      <div className="flex items-start justify-between">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{title}</div>
      </div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <div className="text-xl font-semibold font-mono">{value ?? "—"}</div>
        <Sparkline data={series} width={64} height={22} stroke={stroke} />
      </div>
    </Card>
  );
}

function DT({ k, v, mono }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className={mono ? "font-mono text-right" : "text-right"}>{v ?? "—"}</dd>
    </>
  );
}

function Status({ icon: Icon, label, value, tone = "ok" }) {
  const toneColor = tone === "warn" ? "text-amber-400" : "text-emerald-400";
  return (
    <div className="flex items-center gap-2 rounded border border-border px-3 py-2">
      <Icon className={`h-4 w-4 ${toneColor}`} />
      <div className="flex flex-col leading-tight">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
        <span className="font-mono">{value}</span>
      </div>
    </div>
  );
}

function formatUptime(s) {
  if (!s) return "0s";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${Math.floor(s % 60)}s`;
  return `${Math.floor(s)}s`;
}