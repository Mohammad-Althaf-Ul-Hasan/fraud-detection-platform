export default function Sparkline({ data = [], width = 80, height = 24, stroke = "#3b82f6" }) {
  if (!data || data.length < 2) {
    return <svg width={width} height={height} />;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);
  const points = data
    .map((v, i) => `${(i * stepX).toFixed(2)},${(height - ((v - min) / span) * height).toFixed(2)}`)
    .join(" ");
  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}