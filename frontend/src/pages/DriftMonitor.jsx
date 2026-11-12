import { useEffect, useState } from "react";
import { endpoints } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, AlertTriangle, ExternalLink, RefreshCw } from "lucide-react";
import { toast } from "sonner";

export default function DriftMonitor() {
  const [drift, setDrift] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function load() {
    try {
      const d = await endpoints.drift();
      setDrift(d);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  async function handleRetrain() {
    toast.info("Retraining is out of scope for the UI", {
      description:
        "Run `python scripts/retrain_trigger.py --auto-reload` on the host to retrain.",
    });
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Drift Monitor</h1>
          <p className="text-sm text-muted-foreground">
            Evidently · reference vs live distribution · refreshes every 5 s
          </p>
        </div>
        <Badge variant="outline" className="text-[10px]">
          <Activity className="h-2.5 w-2.5 mr-1" /> auto
        </Badge>
      </div>

      {error && <div className="text-sm text-red-400">Error: {error}</div>}

      {loading && <Skeleton className="h-64 w-full" />}

      {!loading && drift?.report_exists === false && (
        <Card className="p-8 text-center">
          <AlertTriangle className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <h2 className="text-base font-semibold mb-1">No drift report available</h2>
          <p className="text-sm text-muted-foreground mb-4 max-w-md mx-auto">
            Run <code className="font-mono text-xs px-1.5 py-0.5 rounded bg-muted">python scripts/drift_monitor.py</code> on the host to generate a report.
            It will appear here after the next refresh.
          </p>
        </Card>
      )}

      {!loading && drift?.report_exists && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card className="p-4">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Drift share
              </div>
              <div className="mt-1 text-2xl font-semibold font-mono">
                {(drift.drift_share * 100).toFixed(1)}%
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Drifted columns
              </div>
              <div className="mt-1 text-2xl font-semibold font-mono">
                {drift.drifted_columns} / {drift.total_columns}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Retrain
              </div>
              <div className="mt-1">
                {drift.retrain_recommended ? (
                  <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/30">
                    <AlertTriangle className="h-3 w-3 mr-1" /> recommended
                  </Badge>
                ) : (
                  <Badge variant="outline" className="text-emerald-400 border-emerald-500/30">
                    not needed
                  </Badge>
                )}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Generated
              </div>
              <div className="mt-1 text-xs font-mono text-muted-foreground">
                {drift.generated_at
                  ? drift.generated_at.slice(0, 19).replace("T", " ")
                  : "—"}
              </div>
            </Card>
          </div>

          <Card className="p-4">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-sm font-semibold">Latest report</h2>
                <p className="text-xs text-muted-foreground">
                  Reference {drift.reference_rows?.toLocaleString() ?? "—"} rows ·
                  Current {drift.current_rows?.toLocaleString() ?? "—"} rows
                  {drift.simulated_drift && (
                    <span className="ml-2 text-amber-400">· simulated</span>
                  )}
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={load}>
                <RefreshCw className="h-3 w-3 mr-1.5" /> Refresh
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <div className="text-muted-foreground mb-1">Threshold</div>
                <div className="font-mono">{drift.threshold}</div>
              </div>
              <div>
                <div className="text-muted-foreground mb-1">HTML report</div>
                <div className="font-mono text-[10px] truncate">
                  {drift.report_html_path || "—"}
                </div>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-2">
              <Button
                size="sm"
                variant={drift.retrain_recommended ? "default" : "outline"}
                onClick={handleRetrain}
              >
                <RefreshCw className="h-3 w-3 mr-1.5" /> Retrain (host only)
              </Button>
              <p className="text-[10px] text-muted-foreground">
                Retrain runs a host-side script — not callable from this container.
              </p>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}