import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { endpoints } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet";
import EmptyState from "@/components/EmptyState";
import RingTimeline from "@/components/RingTimeline";
import {
  AlertTriangle, ExternalLink, RefreshCw, Users,
} from "lucide-react";

function SuspicionPill({ score }) {
  const level =
    score >= 0.6 ? "high" :
    score >= 0.3 ? "medium" : "low";
  const styles = {
    high:   "bg-red-500/15 text-red-400 border-red-500/30",
    medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    low:    "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  };
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[11px] ${styles[level]}`}>
      {score.toFixed(3)}
    </span>
  );
}

function CategoryBadge({ category, ringIds }) {
  if (category === "simulated") {
    return (
      <Badge variant="outline" className="text-[10px] border-red-500/30 text-red-400 bg-red-500/5">
        <AlertTriangle className="h-2.5 w-2.5 mr-1" /> simulated
      </Badge>
    );
  }
  if (category === "novel") {
    return (
      <Badge variant="outline" className="text-[10px] border-violet-500/30 text-violet-400 bg-violet-500/5">
        novel
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-[10px] border-emerald-500/30 text-emerald-400 bg-emerald-500/5">
      {ringIds?.join(", ") || "labeled"}
    </Badge>
  );
}

export default function Rings() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [selectedRing, setSelectedRing] = useState(null);

  async function load(force = false) {
    if (force) setRefreshing(true);
    else setLoading(true);
    try {
      const res = await endpoints.discoveredRings(force);
      setData(res);
      setError(null);
      if (force) toast.success("Discovery complete");
    } catch (e) {
      setError(e.message);
      if (force) toast.error("Refresh failed", { description: e.message });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => { load(false); }, []);

  function handleRowClick(c) {
    if (c.ring_ids && c.ring_ids.length > 0) {
      setSelectedRing({ ringId: c.ring_ids[0], cluster: c });
    } else {
      navigate(`/graph?account=${c.sample_accounts[0]}`);
    }
  }

  if (error) return <div className="p-6 text-red-400">Error: {error}</div>;

  if (loading && !data) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Ring Discovery</h1>
          <p className="text-xs text-muted-foreground">
            Unsupervised clustering on device/card sharing · click any row to replay its lifecycle
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => load(true)}
          disabled={refreshing}
        >
          <RefreshCw className={`h-3 w-3 mr-1.5 ${refreshing ? "animate-spin" : ""}`} />
          {refreshing ? "Discovering..." : "Refresh"}
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-3">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Clusters found
          </div>
          <div className="mt-1 text-2xl font-semibold font-mono">
            {data.total_clusters}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Original labeled
          </div>
          <div className="mt-1 text-2xl font-semibold font-mono text-emerald-400">
            {data.clusters.filter((c) => c.category === "original").length}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Simulated attacks
          </div>
          <div className="mt-1 text-2xl font-semibold font-mono text-red-400">
            {data.clusters.filter((c) => c.category === "simulated").length}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Novel (unlabeled)
          </div>
          <div className="mt-1 text-2xl font-semibold font-mono text-violet-400">
            {data.clusters.filter((c) => c.category === "novel").length}
          </div>
        </Card>
      </div>

      {data.generated_at && (
        <div className="text-[10px] text-muted-foreground">
          Last run: {data.generated_at.slice(0, 19).replace("T", " ")} UTC
        </div>
      )}

      <Card className="overflow-hidden">
        <div className="border-b border-border px-4 py-2">
          <h2 className="text-sm font-semibold">Discovered clusters</h2>
          <p className="text-[10px] text-muted-foreground">
            Ranked by suspicion = avg(GNN) × log(size+1). Click a row to open the timeline replay.
          </p>
        </div>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[90px]">Cluster</TableHead>
              <TableHead className="text-right">Size</TableHead>
              <TableHead className="text-right">Avg GNN</TableHead>
              <TableHead className="text-right">Suspicion</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Shared device</TableHead>
              <TableHead className="w-[60px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.clusters.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="p-0">
                  <EmptyState
                    icon={Users}
                    title="No clusters found"
                    description="Run the attack simulator first, then refresh."
                  />
                </TableCell>
              </TableRow>
            )}
            {data.clusters.map((c) => (
              <TableRow
                key={c.cluster_id}
                className="cursor-pointer hover:bg-muted/30"
                onClick={() => handleRowClick(c)}
              >
                <TableCell className="font-mono text-[11px]">
                  #{c.cluster_id}
                </TableCell>
                <TableCell className="text-right font-mono text-[11px]">
                  {c.size}
                </TableCell>
                <TableCell className="text-right font-mono text-[11px]">
                  {c.avg_gnn.toFixed(3)}
                </TableCell>
                <TableCell className="text-right">
                  <SuspicionPill score={c.suspicion_score} />
                </TableCell>
                <TableCell>
                  <CategoryBadge category={c.category} ringIds={c.ring_ids} />
                </TableCell>
                <TableCell className="font-mono text-[10px] text-muted-foreground truncate max-w-[160px]">
                  {c.shared_device}
                </TableCell>
                <TableCell>
                  <Button
                    asChild
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Link to={`/graph?account=${c.sample_accounts[0]}`}>
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {data.unlabeled_suspects.length > 0 && (
        <Card className="overflow-hidden">
          <div className="border-b border-border px-4 py-2">
            <h2 className="text-sm font-semibold">Unlabeled suspects</h2>
            <p className="text-[10px] text-muted-foreground">
              High GNN scores but not part of any known cluster — fresh leads for investigation.
            </p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 p-4">
            {data.unlabeled_suspects.map((s) => (
              <Link
                key={s.account_id}
                to={`/graph?account=${s.account_id}`}
                className="rounded border border-amber-500/20 bg-amber-500/5 p-2 hover:border-amber-500/40 transition-colors"
              >
                <div className="font-mono text-[10px] text-muted-foreground truncate">
                  {s.account_id}
                </div>
                <div className="font-mono text-sm font-semibold text-amber-400">
                  {s.gnn_score.toFixed(3)}
                </div>
              </Link>
            ))}
          </div>
        </Card>
      )}

      {/* Replay timeline Sheet */}
      <Sheet
        open={!!selectedRing}
        onOpenChange={(open) => !open && setSelectedRing(null)}
      >
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
          {selectedRing && (
            <>
              <SheetHeader>
                <SheetTitle className="text-sm">
                  Ring lifecycle replay
                </SheetTitle>
                <SheetDescription className="text-[11px]">
                  Scrub through the events that formed and detected this ring.
                </SheetDescription>
              </SheetHeader>
              <div className="mt-4">
                <RingTimeline ringId={selectedRing.ringId} />
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}