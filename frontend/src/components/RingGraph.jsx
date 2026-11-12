export default function RingGraph({ graph }) {
  const W = 520, H = 420;
  const cx = W / 2, cy = H / 2;
  const radius = 130;

  const others = graph.neighbors.filter((n) => n !== graph.account_id);
  const n = others.length;

  const accountPos = others.map((id, i) => {
    const angle = (2 * Math.PI * i) / Math.max(n, 1) - Math.PI / 2;
    return {
      id,
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    };
  });

  const selfPos   = { x: cx, y: cy };
  const devicePos = { x: cx + radius + 80, y: cy };
  const cardPos   = { x: cx - radius - 80, y: cy };

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
      {/* Labels */}
      <text x={12} y={22} fontSize={12} fill="#cbd5e1" fontWeight="600">
        {graph.is_ring_member ? `Ring: ${graph.ring_id}` : "Not a ring member"}
      </text>
      <text x={12} y={40} fontSize={11} fill="#94a3b8">
        GNN score:{" "}
        {graph.gnn_score != null ? graph.gnn_score.toFixed(4) : "N/A"}
      </text>

      {/* Edges: self → device, self → card */}
      <line x1={selfPos.x} y1={selfPos.y} x2={devicePos.x} y2={devicePos.y}
            stroke="#64748b" strokeWidth={2} />
      <line x1={selfPos.x} y1={selfPos.y} x2={cardPos.x} y2={cardPos.y}
            stroke="#64748b" strokeWidth={2} />

      {/* Edges: other members → device, card */}
      {accountPos.map((p) => (
        <g key={`e-${p.id}`}>
          <line x1={p.x} y1={p.y} x2={devicePos.x} y2={devicePos.y}
                stroke="#475569" strokeWidth={1} opacity={0.6} />
          <line x1={p.x} y1={p.y} x2={cardPos.x} y2={cardPos.y}
                stroke="#475569" strokeWidth={1} opacity={0.6} />
        </g>
      ))}

      {/* Device */}
      <rect x={devicePos.x - 38} y={devicePos.y - 16}
            width={76} height={32} rx={6} fill="#7c3aed" />
      <text x={devicePos.x} y={devicePos.y + 5} textAnchor="middle"
            fontSize={11} fill="white" fontWeight="600">DEVICE</text>

      {/* Card */}
      <rect x={cardPos.x - 32} y={cardPos.y - 16}
            width={64} height={32} rx={6} fill="#7c3aed" />
      <text x={cardPos.x} y={cardPos.y + 5} textAnchor="middle"
            fontSize={11} fill="white" fontWeight="600">CARD</text>

      {/* Other accounts */}
      {accountPos.map((p) => (
        <g key={`a-${p.id}`}>
          <circle cx={p.x} cy={p.y} r={18}
                  fill="#3b82f6" stroke="#1e40af" strokeWidth={2} />
          <text x={p.x} y={p.y + 4} textAnchor="middle"
                fontSize={9} fill="white">
            {p.id.slice(-4)}
          </text>
        </g>
      ))}

      {/* Self */}
      <circle cx={selfPos.x} cy={selfPos.y} r={24}
              fill="#ef4444" stroke="#7f1d1d" strokeWidth={2} />
      <text x={selfPos.x} y={selfPos.y + 4} textAnchor="middle"
            fontSize={10} fill="white" fontWeight="700">
        {graph.account_id.slice(-4)}
      </text>
    </svg>
  );
}