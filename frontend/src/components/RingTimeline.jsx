import { useEffect, useMemo, useRef, useState } from "react";
import { endpoints } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  AlertTriangle, CheckCircle2, CircleDot, CreditCard,
  Pause, Play, RotateCcw, Smartphone, UserPlus, Users,
} from "lucide-react";

const EVENT_ICONS = {
  attack_launched:    AlertTriangle,
  device_seen:        Smartphone,
  account_spawned:    UserPlus,
  coordinated_drain:  CreditCard,
  detected:           CheckCircle2,
  transaction:        CircleDot,
  drain:              CreditCard,
  no_data:            AlertTriangle,
};

const KIND_BADGE = {
  simulated: { label: "Simulated attack", cls: "border-red-500/30 text-red-400 bg-red-500/10" },
  original:  { label: "Original labeled", cls: "border-emerald-500/30 text-emerald-400 bg-emerald-500/10" },
  novel:     { label: "Novel discovery",  cls: "border-violet-500/30 text-violet-400 bg-violet-500/10" },
};

export default function RingTimeline({ ringId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentT, setCurrentT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const listRef = useRef(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setData(null);
    endpoints
      .replayRing(ringId)
      .then((d) => {
        setData(d);
        setCurrentT(d.start_t);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ringId]);

  useEffect(() => {
    if (!playing || !data) return;
    const duration = 8000 / speed;
    const start = data.start_t;
    const end = Math.max(data.end_t, start + 1);
    const span = end - start;
    const t0 = Date.now();

    const timer = setInterval(() => {
      const elapsed = Date.now() - t0;
      const progress = Math.min(elapsed / duration, 1);
      setCurrentT(start + progress * span);
      if (progress >= 1) setPlaying(false);
    }, 40);

    return () => clearInterval(timer);
  }, [playing, data, speed]);

  const eventStates = useMemo(() => {
    if (!data) return {};
    const states = {};
    for (const ev of data.events) {
      const key = `${ev.t}|${ev.type}|${ev.account || ""}`;
      if (ev.t < currentT - 0.01) states[key] = "past";
      else if (Math.abs(ev.t - currentT) < 0.5) states[key] = "active";
      else states[key] = "future";
    }
    return states;
  }, [data, currentT]);

  // Auto-scroll active event into view
  useEffect(() => {
    if (!listRef.current) return;
    const active = listRef.current.querySelector("[data-state='active']");
    if (active) {
      active.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [currentT]);

  function reset() {
    setPlaying(false);
    setCurrentT(data?.start_t ?? 0);
  }

  function jumpTo(t) {
    setPlaying(false);
    setCurrentT(t);
  }

  if (loading) return <Skeleton className="h-96 w-full" />;
  if (error) return <div className="text-red-400 p-4">Error: {error}</div>;
  if (!data) return null;

  const badge = KIND_BADGE[data.kind] || KIND_BADGE.original;
  const span = Math.max(data.end_t - data.start_t, 1);
  const progress = Math.max(0, Math.min(1, (currentT - data.start_t) / span));
  const fmtT = (t) => {
    if (data.kind === "simulated") return `T+${Math.round(t)}`;
    return `step ${Math.round(t)}`;
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className={`text-[10px] ${badge.cls}`}>
            {badge.label}
          </Badge>
          <span className="font-mono text-xs text-muted-foreground break-all">
            {data.ring_id}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
          <span className="flex items-center gap-1">
            <Users className="h-3 w-3" />
            {data.members.length} members
          </span>
          {data.stats.total_volume && (
            <span className="font-mono">
              ${data.stats.total_volume.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
          )}
          {data.stats.duration_steps !== undefined && (
            <span>
              {data.stats.duration_steps} step{data.stats.duration_steps !== 1 ? "s" : ""}
            </span>
          )}
          {data.device_id && (
            <span className="font-mono text-[10px] truncate max-w-[180px]">
              {data.device_id}
            </span>
          )}
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={() => setPlaying((p) => !p)}
          disabled={data.events.length === 0}
          className="h-7 px-2"
        >
          {playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
        </Button>
        <Button size="sm" variant="ghost" onClick={reset} className="h-7 px-2">
          <RotateCcw className="h-3 w-3" />
        </Button>
        <div className="flex items-center gap-0.5">
          {[1, 2, 4].map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={cn(
                "text-[10px] px-2 py-1 rounded transition-colors",
                speed === s
                  ? "bg-violet-500/20 text-violet-300"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {s}×
            </button>
          ))}
        </div>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">
          {fmtT(currentT)} / {fmtT(data.end_t)}
        </span>
      </div>

      {/* Scrubber */}
      <div className="relative h-2 rounded-full bg-muted/40">
        <div
          className="absolute top-0 left-0 h-full rounded-full bg-gradient-to-r from-violet-500 to-red-500"
          style={{ width: `${progress * 100}%` }}
        />
        {data.events.map((ev, i) => {
          const pct = ((ev.t - data.start_t) / span) * 100;
          return (
            <button
              key={i}
              onClick={() => jumpTo(ev.t)}
              className="absolute top-1/2 -translate-y-1/2 h-3 w-0.5 rounded bg-foreground/40 hover:bg-foreground/90 transition-colors"
              style={{ left: `calc(${pct}% - 1px)` }}
              title={`${ev.label} @ ${fmtT(ev.t)}`}
            />
          );
        })}
        <div
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-4 w-4 rounded-full bg-white border-2 border-violet-500 shadow-lg shadow-violet-500/40 pointer-events-none"
          style={{ left: `${progress * 100}%` }}
        />
      </div>

      {/* Event cards */}
      <div
        ref={listRef}
        className="space-y-1.5 max-h-[380px] overflow-y-auto pr-1"
      >
        {data.events.map((ev, i) => {
          const Icon = EVENT_ICONS[ev.type] || CircleDot;
          const key = `${ev.t}|${ev.type}|${ev.account || ""}`;
          const state = eventStates[key] || "future";
          return (
            <div
              key={i}
              data-state={state}
              onClick={() => jumpTo(ev.t)}
              className={cn(
                "flex items-start gap-2 rounded border p-2 cursor-pointer transition-all",
                state === "active" && "border-violet-500/50 bg-violet-500/10 shadow-sm",
                state === "past" && "border-border/40 bg-muted/20",
                state === "future" && "border-border/15 opacity-40"
              )}
            >
              <Icon className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium">{ev.label}</span>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {fmtT(ev.t)}
                  </span>
                  {ev.amount != null && (
                    <span className="text-[10px] font-mono text-amber-400">
                      ${Number(ev.amount).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </span>
                  )}
                </div>
                {ev.account && (
                  <div className="text-[10px] font-mono text-muted-foreground truncate">
                    {ev.account}
                  </div>
                )}
                {ev.detail && (
                  <div className="text-[10px] text-muted-foreground">
                    {ev.detail}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}