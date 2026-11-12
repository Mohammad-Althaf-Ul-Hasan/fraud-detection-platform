import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { endpoints } from "@/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ResizableHandle, ResizablePanel, ResizablePanelGroup,
} from "@/components/ui/resizable";
import RingGraph3D from "@/components/RingGraph3D";
import NarrativeCard from "@/components/NarrativeCard";
import CounterfactualPanel from "@/components/CounterfactualPanel";
import { ArrowLeft, CheckCircle2, ExternalLink, Flag, XCircle } from "lucide-react";

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

function ShapRow({ feature, shap }) {
  const pos = shap >= 0;
  const pct = Math.min(Math.abs(shap) * 200, 100);
  return (
    <div className="grid grid-cols-[1fr_auto_60px] items-center gap-2 text-xs">
      <div className="truncate text-foreground/80" title={feature}>{feature}</div>
      <div className="relative h-2 w-28 rounded bg-muted/40">
        <div
          className={cn("absolute top-0 h-2", pos ? "bg-red-500 rounded-r" : "bg-emerald-500 rounded-l")}
          style={{ left: pos ? "50%" : `${50 - pct / 2}%`, width: `${pct / 2}%` }}
        />
        <div className="absolute left-1/2 top-0 h-2 w-px bg-border" />
      </div>
      <div className={cn("text-right font-mono", pos ? "text-red-400" : "text-emerald-400")}>
        {shap >= 0 ? "+" : ""}{shap.toFixed(3)}
      </div>
    </div>
  );
}

export default function CaseDetail() {
  const { txnId } = useParams();
  const [txn, setTxn] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [graph, setGraph] = useState(null);
  const [caseRow, setCaseRow] = useState(null);
  const [caseExists, setCaseExists] = useState(false);
  const [label, setLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function loadAll() {
    try {
      const t = await endpoints.txn(txnId);
      setTxn(t);
      const [expl, gr, cr] = await Promise.all([
        endpoints.explain(t).catch((e) => ({ error: e.message })),
        endpoints.graph(t.nameOrig).catch((e) => ({ error: e.message })),
        endpoints.case(txnId).catch(() => null),
      ]);
      setExplanation(expl);
      setGraph(gr);
      if (cr) {
        setCaseRow(cr);
        setCaseExists(true);
        setLabel(cr.label || "");
        setNotes(cr.notes || "");
      }
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await loadAll();
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [txnId]);

  async function submitFeedback(newLabel) {
    if (!caseExists) return;
    setSaving(true);
    try {
      await endpoints.feedback({
        txn_id: txnId,
        label: newLabel,
        label_by: "analyst",
        notes,
      });
      setLabel(newLabel);
      setCaseRow((prev) => ({ ...prev, label: newLabel, notes }));
      toast.success(`Case marked ${newLabel.replace("_", " ")}`);
    } catch (e) {
      toast.error("Feedback failed", { description: e.message });
    } finally {
      setSaving(false);
    }
  }

  if (error) {
    return (
      <div className="p-6">
        <Link to="/alerts" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3 w-3" /> Back
        </Link>
        <div className="mt-4 text-red-400">{error}</div>
      </div>
    );
  }

  if (!txn) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-[500px] w-full" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-border px-6 py-3">
        <Link to="/alerts" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3 w-3" /> Back to alerts
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="text-lg font-semibold font-mono">Case {txn.txn_id}</h1>
          <DecisionBadge decision={txn.decision} />
          <span className="text-xs text-muted-foreground font-mono">
            {txn.nameOrig} → {txn.nameDest}
          </span>
          {caseRow?.label && (
            <Badge variant="outline" className="text-[10px] ml-auto">
              labeled: {caseRow.label.replace("_", " ")}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        <ResizablePanelGroup direction="horizontal" className="h-full">
          <ResizablePanel defaultSize={42} minSize={30}>
            <div className="h-full overflow-y-auto p-6 space-y-4">
              <Card className="p-4">
                <h2 className="text-sm font-semibold mb-3">Model scores</h2>
                <div className="grid grid-cols-3 gap-2">
                  <Score label="XGB" value={txn.xgb_probability} />
                  <Score label="GNN" value={txn.gnn_probability} />
                  <Score label="Final" value={txn.fraud_probability} highlight />
                </div>
                <Separator className="my-3" />
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Threshold {txn.threshold?.toFixed(4)}</span>
                  <span className="font-mono">{txn.latency_ms?.toFixed(2)} ms</span>
                </div>
              </Card>
              <NarrativeCard txn={txn} />

              <Card className="p-4">
                <h2 className="text-sm font-semibold mb-3">Top feature contributions (SHAP)</h2>
                {explanation?.top_features ? (
                  <div className="space-y-2">
                    {explanation.top_features.map((f) => (
                      <ShapRow key={f.name} feature={f.name} shap={f.shap_value} />
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">
                    {explanation?.error ? `Unavailable: ${explanation.error}` : "Loading ..."}
                  </div>
                )}
              </Card>

              <Card className="p-4">
                <h2 className="text-sm font-semibold mb-3">Transaction</h2>
                <dl className="grid grid-cols-2 gap-y-1.5 text-xs">
                  <Row k="Type" v={txn.type} />
                  <Row k="Step" v={txn.step} />
                  <Row k="Amount" v={Number(txn.amount).toLocaleString()} />
                  <Row k="Old bal / orig" v={txn.oldbalanceOrg?.toFixed(2)} />
                  <Row k="New bal / orig" v={txn.newbalanceOrig?.toFixed(2)} />
                  <Row k="Old bal / dest" v={txn.oldbalanceDest?.toFixed(2)} />
                  <Row k="New bal / dest" v={txn.newbalanceDest?.toFixed(2)} />
                  <Row k="Truth" v={txn.truth_isFraud === 1 ? "fraud" : "legit"} />
                </dl>
              </Card>

              <Card className="p-4">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-semibold">Analyst review</h2>
                  {caseExists ? (
                    <Badge variant="outline" className="text-[10px]">persisted</Badge>
                  ) : (
                    <Badge variant="outline" className="text-[10px] border-amber-500/30 text-amber-400">
                      below review threshold
                    </Badge>
                  )}
                </div>
                <div className="space-y-3">
                  <Input
                    placeholder="Notes (optional)"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    disabled={!caseExists}
                    className="text-xs h-9"
                  />
                  <div className="grid grid-cols-3 gap-2">
                    <Button
                      size="sm"
                      variant={label === "confirmed_fraud" ? "default" : "outline"}
                      onClick={() => submitFeedback("confirmed_fraud")}
                      disabled={!caseExists || saving}
                      className="text-[11px]"
                    >
                      <CheckCircle2 className="h-3 w-3 mr-1" /> Confirm
                    </Button>
                    <Button
                      size="sm"
                      variant={label === "false_positive" ? "default" : "outline"}
                      onClick={() => submitFeedback("false_positive")}
                      disabled={!caseExists || saving}
                      className="text-[11px]"
                    >
                      <XCircle className="h-3 w-3 mr-1" /> False pos
                    </Button>
                    <Button
                      size="sm"
                      variant={label === "needs_review" ? "default" : "outline"}
                      onClick={() => submitFeedback("needs_review")}
                      disabled={!caseExists || saving}
                      className="text-[11px]"
                    >
                      <Flag className="h-3 w-3 mr-1" /> Review
                    </Button>
                  </div>
                  {!caseExists && (
                    <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 space-y-1">
                      <p className="text-[11px] font-semibold text-amber-400">
                        Below the review threshold
                      </p>
                      <p className="text-[10px] text-muted-foreground leading-relaxed">
                        This txn scored{" "}
                        <span className="font-mono text-foreground">
                          {txn.fraud_probability?.toFixed(4)}
                        </span>{" "}
                        — the review cutoff is{" "}
                        <span className="font-mono text-foreground">
                          {(txn.threshold * 0.5).toFixed(4)}
                        </span>{" "}
                        (50% of the {txn.threshold?.toFixed(4)} BLOCK threshold).
                        Only BLOCK and high-risk ALLOW transactions are persisted
                        to the case database. This transaction is not eligible
                        for analyst labeling.
                      </p>
                    </div>
                  )}
                  {caseRow?.label_at && (
                    <p className="text-[10px] text-muted-foreground">
                      Last labeled {caseRow.label_at.slice(0, 19).replace("T", " ")} by {caseRow.label_by}
                    </p>
                  )}
                </div>
              </Card>
              <CounterfactualPanel txn={txn} />
            </div>
          </ResizablePanel>

          <ResizableHandle withHandle />

          <ResizablePanel defaultSize={58} minSize={30}>
            <div className="h-full flex flex-col p-6">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-sm font-semibold">Account graph</h2>
                  <p className="text-xs text-muted-foreground">
                    {graph?.is_ring_member
                      ? `Ring ${graph.ring_id} — ${graph.neighbors.length} members`
                      : "Not part of a detected ring"}
                  </p>
                </div>
                <Button asChild size="sm" variant="outline">
                  <Link to={`/graph?account=${txn.nameOrig}`}>
                    Open explorer <ExternalLink className="h-3 w-3 ml-1" />
                  </Link>
                </Button>
              </div>
              <div className="flex-1 min-h-0">
                <RingGraph3D graph={graph} height="100%" />
              </div>
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </div>
  );
}

function Score({ label, value, highlight }) {
  return (
    <div className={cn("rounded border p-2",
      highlight ? "border-primary/40 bg-primary/5" : "border-border")}>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-mono text-sm font-semibold mt-0.5">
        {value != null ? value.toFixed(4) : "—"}
      </div>
    </div>
  );
}

function Row({ k, v }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="font-mono text-right">{v ?? "—"}</dd>
    </>
  );
}