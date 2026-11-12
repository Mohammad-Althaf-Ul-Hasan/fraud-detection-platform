import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { endpoints } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import RingGraph3D from "@/components/RingGraph3D";
import { GitBranch, Search } from "lucide-react";

export default function GraphView() {
  const [params] = useSearchParams();
  const [accountId, setAccountId] = useState(params.get("account") || "");
  const [rings, setRings] = useState({});
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function load(id) {
    if (!id) return;
    setLoading(true); setError(null);
    try {
      const data = await endpoints.graph(id);
      setGraph(data);
      setAccountId(id);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const r = await endpoints.rings().catch(() => ({ rings: {} }));
        if (cancelled) return;
        setRings(r.rings || {});
        if (!params.get("account")) {
          const firstRing = Object.keys(r.rings || {})[0];
          const firstMember = firstRing ? r.rings[firstRing][0] : null;
          if (firstMember) load(firstMember);
        } else {
          load(params.get("account"));
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    }
    bootstrap();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const allMembers = Object.values(rings).flat();

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Graph Explorer</h1>
          <p className="text-sm text-muted-foreground">
            3D view of account ↔ device ↔ card relationships
          </p>
        </div>
        {graph?.is_ring_member && (
          <Badge variant="outline" className="border-amber-500/40 text-amber-400">
            Ring {graph.ring_id}
          </Badge>
        )}
      </div>

      <Card className="p-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            placeholder="Account ID (e.g. C1401017541)"
            className="pl-8 font-mono text-xs h-9"
            onKeyDown={(e) => { if (e.key === "Enter") load(accountId); }}
          />
        </div>
        <Button onClick={() => load(accountId)} size="sm">
          <GitBranch className="h-3.5 w-3.5 mr-1.5" /> Load
        </Button>
        <select
          onChange={(e) => { if (e.target.value) load(e.target.value); }}
          value={allMembers.includes(accountId) ? accountId : ""}
          className="h-9 rounded-md border border-input bg-transparent px-3 text-xs font-mono"
        >
          <option value="">Jump to ring member...</option>
          {Object.entries(rings).map(([rid, members]) =>
            members.map((m) => (
              <option key={m} value={m}>{rid} — {m}</option>
            ))
          )}
        </select>
      </Card>

      {error && <div className="text-sm text-red-400">{error}</div>}

      <Card className="overflow-hidden">
        {loading ? (
          <Skeleton className="h-[560px] w-full" />
        ) : graph ? (
          <RingGraph3D graph={graph} height={560} />
        ) : (
          <div className="h-[560px] flex items-center justify-center text-sm text-muted-foreground">
            Enter an account ID or pick a ring member
          </div>
        )}
      </Card>

      {graph && (
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Ring" value={graph.ring_id || "—"} />
          <Stat label="Device" value={graph.device_id} />
          <Stat label="GNN score" value={graph.gnn_score?.toFixed(4) ?? "—"} />
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <Card className="p-3">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-mono text-sm mt-1 truncate" title={value}>{value}</div>
    </Card>
  );
}