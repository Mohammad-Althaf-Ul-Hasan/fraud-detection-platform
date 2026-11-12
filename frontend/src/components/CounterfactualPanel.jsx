import { useEffect, useState } from "react";
import { endpoints } from "@/api";
import Slider from "./Slider";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  ArrowRight, RotateCcw, Sparkles, TrendingDown, TrendingUp,
} from "lucide-react";

function formatMoney(v) {
  return `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export default function CounterfactualPanel({ txn }) {
  const [init, setInit] = useState(null);
  const [amount, setAmount] = useState(txn.amount);
  const [count, setCount] = useState(0);
  const [priorAvg, setPriorAvg] = useState(0);
  const [destHasHistory, setDestHasHistory] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await endpoints.counterfactual({ txn_id: txn.txn_id });
        if (cancelled) return;
        setInit(r);
        setAmount(r.baseline_features.amount);
        setCount(r.baseline_features.orig_count_24h);
        setPriorAvg(r.baseline_features.orig_prior_avg_amount);
        setDestHasHistory(r.baseline_features.dest_has_history);
        setResult(r);
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => { cancelled = true; };
  }, [txn.txn_id]);

  useEffect(() => {
    if (!init) return;
    const timer = setTimeout(async () => {
      try {
        const res = await endpoints.counterfactual({
          txn_id: txn.txn_id,
          amount,
          orig_count_24h: Math.round(count),
          orig_prior_avg_amount: priorAvg,
          dest_has_history: destHasHistory,
        });
        setResult(res);
      } catch (e) {
        setError(e.message);
      }
    }, 150);
    return () => clearTimeout(timer);
  }, [txn.txn_id, init, amount, count, priorAvg, destHasHistory]);

  const baseline = txn.fraud_probability ?? 0;
  const cf = result?.counterfactual_probability ?? baseline;
  const delta = cf - baseline;
  const decisionChanges = result?.would_change_decision;
  const maxAmount = Math.max(txn.amount * 3, init?.baseline_features?.amount * 3 || 10000);
  const maxPriorAvg = Math.max(txn.amount * 3, 10000);

  function reset() {
    if (!init) return;
    setAmount(init.baseline_features.amount);
    setCount(init.baseline_features.orig_count_24h);
    setPriorAvg(init.baseline_features.orig_prior_avg_amount);
    setDestHasHistory(init.baseline_features.dest_has_history);
  }

  return (
    <Card className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-violet-400" />
          <h2 className="text-sm font-semibold">What-if analysis</h2>
        </div>
        <button
          onClick={reset}
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
        >
          <RotateCcw className="h-2.5 w-2.5" /> Reset
        </button>
      </div>

      {error && <div className="text-xs text-red-400">{error}</div>}

      <div className="rounded border border-border/60 bg-muted/20 p-3 grid grid-cols-[1fr_auto_1fr] gap-3 items-center">
        <div className="text-center">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Baseline
          </div>
          <div className="font-mono text-lg font-semibold mt-0.5">
            {baseline.toFixed(4)}
          </div>
          <Badge variant="outline" className="mt-1 text-[9px]">{txn.decision}</Badge>
        </div>
        <ArrowRight className="h-4 w-4 text-muted-foreground" />
        <div className="text-center">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Counterfactual
          </div>
          <div
            className={`font-mono text-lg font-semibold mt-0.5 ${
              delta < 0 ? "text-emerald-400" : delta > 0 ? "text-red-400" : ""
            }`}
          >
            {cf.toFixed(4)}
          </div>
          <Badge
            variant={result?.counterfactual_decision === "BLOCK" ? "destructive" : "outline"}
            className="mt-1 text-[9px]"
          >
            {result?.counterfactual_decision ?? "—"}
          </Badge>
        </div>
      </div>

      {init && (
        <div className="space-y-3 pt-1">
          <Slider label="Amount" value={amount} onChange={setAmount}
                  min={0} max={maxAmount} step={maxAmount / 200}
                  formatValue={formatMoney} />
          <Slider label="Prior txns (24h)" value={count} onChange={setCount}
                  min={0} max={100} step={1} />
          <Slider label="Prior avg amount" value={priorAvg} onChange={setPriorAvg}
                  min={0} max={maxPriorAvg} step={maxPriorAvg / 200}
                  formatValue={formatMoney} />
          <label className="flex items-center justify-between cursor-pointer">
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Destination has prior history
            </span>
            <input
              type="checkbox"
              checked={destHasHistory}
              onChange={(e) => setDestHasHistory(e.target.checked)}
              className="h-3.5 w-3.5 accent-violet-500"
            />
          </label>
        </div>
      )}

      {decisionChanges ? (
        <div className="flex items-center gap-2 text-xs text-violet-300 bg-violet-500/10 border border-violet-500/30 rounded p-2">
          <Sparkles className="h-3 w-3" />
          <span className="font-medium">
            Decision flips from {txn.decision} to {result?.counterfactual_decision}
          </span>
        </div>
      ) : delta !== 0 ? (
        <div className={`flex items-center gap-2 text-xs ${delta < 0 ? "text-emerald-400" : "text-red-400"}`}>
          {delta < 0 ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
          <span>
            {delta < 0 ? "Lowers" : "Raises"} risk by{" "}
            <span className="font-mono font-semibold">
              {Math.abs(delta * 100).toFixed(1)} pp
            </span>
          </span>
        </div>
      ) : null}
    </Card>
  );
}