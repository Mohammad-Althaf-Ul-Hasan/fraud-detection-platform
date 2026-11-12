import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D from "react-force-graph-3d";

const COLOR = {
  selfRiskHigh: "#ef4444",
  selfRiskMed:  "#f59e0b",
  selfRiskLow:  "#64748b",
  neighbor:     "#3b82f6",
  device:       "#a855f7",
  card:         "#ec4899",
  link:         "#475569",
};

function buildGraphData(graph) {
  if (!graph) return { nodes: [], links: [] };

  const gnn = graph.gnn_score ?? 0;
  const selfColor =
    gnn >= 0.5 ? COLOR.selfRiskHigh :
    gnn >= 0.2 ? COLOR.selfRiskMed  : COLOR.selfRiskLow;

  const nodes = [
    { id: graph.account_id, label: graph.account_id, role: "self",
      color: selfColor, val: 14 + gnn * 8 },
    { id: graph.device_id,  label: "device", role: "device",
      color: COLOR.device, val: 10 },
    { id: graph.card_id,    label: "card",   role: "card",
      color: COLOR.card,   val: 10 },
  ];

  const links = [
    { source: graph.account_id, target: graph.device_id, color: COLOR.link },
    { source: graph.account_id, target: graph.card_id,   color: COLOR.link },
  ];

  const others = (graph.neighbors || []).filter((n) => n !== graph.account_id);
  for (const neighbor of others) {
    nodes.push({ id: neighbor, label: neighbor, role: "neighbor",
                 color: COLOR.neighbor, val: 9 });
    links.push({ source: neighbor, target: graph.device_id, color: COLOR.link });
    links.push({ source: neighbor, target: graph.card_id,   color: COLOR.link });
  }

  const seen = new Set();
  const uniqueNodes = [];
  for (const n of nodes) {
    if (!seen.has(n.id)) { seen.add(n.id); uniqueNodes.push(n); }
  }

  return { nodes: uniqueNodes, links };
}

export default function RingGraph3D({ graph, height = 460 }) {
  const fgRef = useRef(null);
  const [mounted, setMounted] = useState(false);

  const data = useMemo(() => buildGraphData(graph), [graph]);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (!fgRef.current || data.nodes.length === 0) return;
    const t = setTimeout(() => {
      try { fgRef.current.zoomToFit(600, 40); } catch { /* scene not ready */ }
    }, 400);
    return () => clearTimeout(t);
  }, [data]);

  if (!graph) {
    return (
      <div className="flex items-center justify-center text-sm text-muted-foreground"
           style={{ height }}>
        No graph data
      </div>
    );
  }

  return (
    <div className="relative rounded-lg border border-border overflow-hidden bg-[#0a0a0a]"
         style={{ height }}>
      {mounted && (
        <ForceGraph3D
          ref={fgRef}
          graphData={data}
          backgroundColor="#0a0a0a"
          showNavInfo={false}
          nodeRelSize={6}
          nodeColor={(n) => n.color}
          nodeVal={(n) => n.val}
          nodeOpacity={0.95}
          nodeLabel={(n) => `${n.role}: ${n.label}`}
          linkColor={(l) => l.color}
          linkOpacity={0.45}
          linkWidth={1.2}
          linkDirectionalParticles={1}
          linkDirectionalParticleWidth={1.2}
          linkDirectionalParticleSpeed={0.004}
          enableNodeDrag={true}
          enableNavigationControls={true}
          controlType="orbit"
          onNodeClick={(node) => {
            if (!fgRef.current) return;
            const dist = 60;
            const ratio = 1 + dist / Math.hypot(node.x, node.y, node.z);
            fgRef.current.cameraPosition(
              { x: node.x * ratio, y: node.y * ratio, z: node.z * ratio },
              node, 1000
            );
          }}
        />
      )}
      <div className="absolute bottom-2 left-2 flex items-center gap-3 text-[10px] text-muted-foreground bg-background/70 backdrop-blur px-2 py-1 rounded">
        <LegendDot color={COLOR.selfRiskHigh} label="High risk" />
        <LegendDot color={COLOR.neighbor}     label="Neighbor" />
        <LegendDot color={COLOR.device}       label="Device" />
        <LegendDot color={COLOR.card}         label="Card" />
      </div>
    </div>
  );
}

function LegendDot({ color, label }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}