import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { endpoints } from "@/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RefreshCw, CheckCircle2, GitBranch } from "lucide-react";

function statusBadge(status) {
  const map = {
    FINISHED: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    RUNNING: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    FAILED: "bg-red-500/15 text-red-400 border-red-500/30",
    KILLED: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  };
  return map[status] || "bg-slate-500/15 text-slate-400 border-slate-500/30";
}

export default function ModelVersions() {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reloading, setReloading] = useState(false);

  async function load() {
    try {
      const d = await endpoints.models();
      setData(d);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  async function handleReload() {
    setReloading(true);
    try {
      const r = await endpoints.reload();
      toast.success(`Promoted run ${r.current_run_id?.slice(0, 8)}`, {
        description: `threshold ${r.threshold?.toFixed(4)}`,
      });
      await load();
    } catch (e) {
      toast.error("Reload failed", { description: e.message });
    } finally {
      setReloading(false);
    }
  }

  const filtered = useMemo(() => {
    if (!data?.runs) return [];
    if (tab === "all") return data.runs;
    return data.runs.filter((r) => r.kind === tab);
  }, [data, tab]);

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Model Versions</h1>
          <p className="text-sm text-muted-foreground">
            MLflow run timeline · auto-refreshes every 15 s
          </p>
        </div>
        <Button size="sm" onClick={handleReload} disabled={reloading}>
          <RefreshCw className={`h-3 w-3 mr-1.5 ${reloading ? "animate-spin" : ""}`} />
          {reloading ? "Reloading…" : "Reload latest"}
        </Button>
      </div>

      <div className="flex items-center gap-3">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="xgboost">XGBoost</TabsTrigger>
            <TabsTrigger value="gnn">GNN</TabsTrigger>
          </TabsList>
        </Tabs>
        {tab === "gnn" && (
          <span className="text-[10px] text-muted-foreground">
            GNN runs serve via Redis cache, not the live scorer
          </span>
        )}
      </div>

      {error && <div className="text-sm text-red-400">Error: {error}</div>}

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[100px]">Status</TableHead>
              <TableHead>Run</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead className="text-right">PR-AUC</TableHead>
              <TableHead className="text-right">Threshold</TableHead>
              <TableHead>Started</TableHead>
              <TableHead className="w-[80px]"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && Array.from({ length: 5 }).map((_, i) => (
              <TableRow key={i}>
                {Array.from({ length: 7 }).map((_, j) => (
                  <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                ))}
              </TableRow>
            ))}
            {!loading && filtered.map((r) => (
              <TableRow key={r.run_id}>
                <TableCell>
                  <Badge className={cn("text-[10px]", statusBadge(r.status))}>
                    {r.status}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">{r.run_id.slice(0, 12)}</span>
                    {r.run_name && (
                      <span className="text-[10px] text-muted-foreground">{r.run_name}</span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-[10px]">
                    <GitBranch className="h-2.5 w-2.5 mr-1" /> {r.kind}
                  </Badge>
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {r.pr_auc != null ? r.pr_auc.toFixed(4) : "—"}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {r.threshold != null ? r.threshold.toFixed(4) : "—"}
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {r.start_time ? r.start_time.slice(0, 19).replace("T", " ") : "—"}
                </TableCell>
                <TableCell>
                  {r.is_current && (
                    <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 text-[10px]">
                      <CheckCircle2 className="h-2.5 w-2.5 mr-1" /> live
                    </Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {!loading && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-12 text-center text-sm text-muted-foreground">
                  No runs in this filter.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}