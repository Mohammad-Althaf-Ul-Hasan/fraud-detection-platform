import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { endpoints } from "@/api";
import { useAlertStream } from "@/hooks/useAlertStream";
import { rowEnter } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import EmptyState from "@/components/EmptyState";
import SimulateAttackButton from "@/components/SimulateAttackButton";
import { AlertTriangle, ArrowUpRight, Search } from "lucide-react";

function RiskPill({ prob, threshold }) {
  const ratio = threshold > 0 ? prob / threshold : 0;
  const level =
    prob >= threshold ? "critical" :
    ratio >= 0.9 ? "high" :
    ratio >= 0.5 ? "medium" : "low";
  const styles = {
    critical: "bg-red-500/15 text-red-400 border-red-500/30",
    high:     "bg-amber-500/15 text-amber-400 border-amber-500/30",
    medium:   "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    low:      "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px]",
        styles[level]
      )}
    >
      {prob.toFixed(3)}
    </span>
  );
}

function DecisionBadge({ decision }) {
  return (
    <Badge
      variant={decision === "BLOCK" ? "destructive" : "outline"}
      className={cn(
        "text-[10px] font-semibold",
        decision === "ALLOW" && "border-emerald-500/30 text-emerald-400"
      )}
    >
      {decision}
    </Badge>
  );
}

export default function LiveAlerts() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { connected, alerts: txns } = useAlertStream(200);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState(params.get("q") || "");
  const [selected, setSelected] = useState(null);
  const [selectedTxnId, setSelectedTxnId] = useState(null);
  const [pulsing, setPulsing] = useState(new Set());

  const threshold = txns[0]?.threshold ?? 0.9897;

  // Detect freshly arrived BLOCK txns to animate their pulse
  const prevIdsRef = useRef(new Set());
  useEffect(() => {
    const newBlocks = [];
    for (const t of txns) {
      if (!prevIdsRef.current.has(t.txn_id)) {
        prevIdsRef.current.add(t.txn_id);
        if (t.decision === "BLOCK") newBlocks.push(t.txn_id);
      }
    }
    if (newBlocks.length) {
      setPulsing(new Set(newBlocks));
      const timer = setTimeout(() => setPulsing(new Set()), 1800);
      return () => clearTimeout(timer);
    }
  }, [txns]);

  const visible = useMemo(() => {
    let rows = txns;
    if (filter === "blocked") rows = rows.filter((t) => t.decision === "BLOCK");
    if (filter === "high") rows = rows.filter((t) => t.fraud_probability >= threshold * 0.9);
    if (filter === "review")
      rows = rows.filter(
        (t) => t.fraud_probability >= threshold * 0.5 && t.decision === "ALLOW"
      );
    if (query) {
      const q = query.toLowerCase();
      rows = rows.filter(
        (t) =>
          t.txn_id.toLowerCase().includes(q) ||
          t.nameOrig.toLowerCase().includes(q) ||
          t.nameDest?.toLowerCase().includes(q)
      );
    }
    return rows;
  }, [txns, filter, query, threshold]);

  const counts = useMemo(
    () => ({
      all: txns.length,
      blocked: txns.filter((t) => t.decision === "BLOCK").length,
      high: txns.filter((t) => t.fraud_probability >= threshold * 0.9).length,
      review: txns.filter(
        (t) => t.fraud_probability >= threshold * 0.5 && t.decision === "ALLOW"
      ).length,
    }),
    [txns, threshold]
  );

  // j/k navigation over visible rows
  useEffect(() => {
    function handler(e) {
      const target = e.target;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        const currentIdx = selectedTxnId
          ? visible.findIndex((t) => t.txn_id === selectedTxnId)
          : -1;
        const nextIdx =
          e.key === "j"
            ? Math.min(currentIdx + 1, visible.length - 1)
            : Math.max(currentIdx - 1, 0);
        if (visible[nextIdx]) setSelectedTxnId(visible[nextIdx].txn_id);
      }
      if (e.key === "e" && selectedTxnId) {
        e.preventDefault();
        navigate(`/case/${selectedTxnId}`);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedTxnId, visible, navigate]);

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Live Alerts
          </h1>
          <p className="text-xs text-muted-foreground">
            Streaming from Kafka via WebSocket · {txns.length} events buffered
            · <kbd className="cmd-k ml-1">J</kbd>
            <kbd className="cmd-k ml-0.5">K</kbd> navigate · <kbd className="cmd-k ml-0.5">E</kbd> open
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Tabs value={filter} onValueChange={setFilter}>
          <TabsList className="h-8">
            <TabsTrigger value="all" className="text-xs">
              All <span className="ml-1 text-[10px] text-muted-foreground">{counts.all}</span>
            </TabsTrigger>
            <TabsTrigger value="blocked" className="text-xs">
              Blocked <span className="ml-1 text-[10px] text-muted-foreground">{counts.blocked}</span>
            </TabsTrigger>
            <TabsTrigger value="high" className="text-xs">
              High risk <span className="ml-1 text-[10px] text-muted-foreground">{counts.high}</span>
            </TabsTrigger>
            <TabsTrigger value="review" className="text-xs">
              Pending <span className="ml-1 text-[10px] text-muted-foreground">{counts.review}</span>
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="relative ml-auto w-64">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter by account or txn…"
            className="h-8 pl-8 text-sm"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <SimulateAttackButton />
      </div>

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[90px]">Txn</TableHead>
              <TableHead>Account</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead className="text-right">XGB</TableHead>
              <TableHead className="text-right">GNN</TableHead>
              <TableHead className="text-right">Final</TableHead>
              <TableHead>Decision</TableHead>
              <TableHead className="text-right">Latency</TableHead>
              <TableHead className="w-[32px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {txns.length === 0 && Array.from({ length: 6 }).map((_, i) => (
              <TableRow key={i}>
                {Array.from({ length: 9 }).map((__, j) => (
                  <TableCell key={j}>
                    <Skeleton className="h-4 w-full" />
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {visible.map((t) => {
              const isSelected = t.txn_id === selectedTxnId;
              const isPulsing = pulsing.has(t.txn_id);
              return (
                <motion.tr
                  key={t.txn_id}
                  initial={rowEnter.initial}
                  animate={rowEnter.animate}
                  data-state={isSelected ? "selected" : undefined}
                  onClick={() => setSelected(t)}
                  className={cn(
                    "cursor-pointer border-b border-border/60 transition-colors density-row",
                    isSelected && "bg-accent/10",
                    isPulsing && "pulse-block"
                  )}
                >
                  <TableCell className="font-mono text-[11px] text-muted-foreground">
                    {t.txn_id}
                  </TableCell>
                  <TableCell className="font-mono text-[11px]">{t.nameOrig}</TableCell>
                  <TableCell className="text-right font-mono text-[11px]">
                    {Number(t.amount ?? 0).toLocaleString(undefined, {
                      maximumFractionDigits: 0,
                    })}
                  </TableCell>
                  <TableCell className="text-right font-mono text-[11px] text-muted-foreground">
                    {t.xgb_probability?.toFixed(4) ?? "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-[11px] text-muted-foreground">
                    {t.gnn_probability != null ? t.gnn_probability.toFixed(4) : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <RiskPill prob={t.fraud_probability} threshold={threshold} />
                  </TableCell>
                  <TableCell>
                    <DecisionBadge decision={t.decision} />
                  </TableCell>
                  <TableCell className="text-right font-mono text-[11px] text-muted-foreground">
                    {t.latency_ms?.toFixed(1)} ms
                  </TableCell>
                  <TableCell>
                    <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                  </TableCell>
                </motion.tr>
              );
            })}
            {txns.length > 0 && visible.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="p-0">
                  <EmptyState
                    icon={AlertTriangle}
                    title="No transactions match this filter"
                    description={
                      query
                        ? `Nothing matched "${query}". Clear the search or try a different filter.`
                        : "Start the Kafka producer to stream transactions into the pipeline."
                    }
                  />
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      <Sheet open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <SheetContent className="w-[420px] sm:w-[480px] overflow-y-auto">
          {selected && (
            <>
              <SheetHeader>
                <SheetTitle className="font-mono text-sm">
                  Txn {selected.txn_id}
                </SheetTitle>
                <SheetDescription className="text-xs">
                  {selected.nameOrig} → {selected.nameDest}
                </SheetDescription>
              </SheetHeader>
              <div className="mt-5 space-y-4">
                <div className="grid grid-cols-3 gap-2">
                  <Metric label="XGB" value={selected.xgb_probability?.toFixed(4)} />
                  <Metric
                    label="GNN"
                    value={
                      selected.gnn_probability != null
                        ? selected.gnn_probability.toFixed(4)
                        : "—"
                    }
                  />
                  <Metric
                    label="Final"
                    value={selected.fraud_probability?.toFixed(4)}
                    highlight
                  />
                </div>
                <div className="flex items-center gap-2">
                  <DecisionBadge decision={selected.decision} />
                  <span className="text-[11px] text-muted-foreground">
                    threshold {threshold.toFixed(4)}
                  </span>
                </div>
                <div className="rounded border border-border/60 p-3 text-xs space-y-1.5">
                  <Row k="Type" v={selected.type} />
                  <Row k="Amount" v={Number(selected.amount ?? 0).toLocaleString()} />
                  <Row k="Step" v={selected.step} />
                  <Row k="Latency" v={`${selected.latency_ms?.toFixed(2)} ms`} />
                </div>
                <Button asChild className="w-full">
                  <Link to={`/case/${selected.txn_id}`}>Open full case</Link>
                </Button>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function Metric({ label, value, highlight }) {
  return (
    <div
      className={cn(
        "rounded border p-2",
        highlight ? "border-violet-500/40 bg-violet-500/5" : "border-border/60"
      )}
    >
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-sm font-semibold">{value ?? "—"}</div>
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{k}</span>
      <span className="font-mono text-[11px]">{v ?? "—"}</span>
    </div>
  );
}