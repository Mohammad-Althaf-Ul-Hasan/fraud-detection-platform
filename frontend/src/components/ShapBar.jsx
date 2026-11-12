export default function ShapBar({ feature, shap }) {
  const pos = shap >= 0;
  const pct = Math.min(Math.abs(shap) * 200, 100); // scale so ~0.5 saturates
  return (
    <div className="flex items-center gap-2 text-xs">
      <div className="w-44 truncate text-gray-300" title={feature}>
        {feature}
      </div>
      <div className="relative flex-1 h-3 bg-slate-800 rounded">
        <div
          className={`absolute top-0 h-3 ${
            pos ? "bg-red-500 rounded-r" : "bg-emerald-500 rounded-l"
          }`}
          style={{
            left: pos ? "50%" : `${50 - pct / 2}%`,
            width: `${pct / 2}%`,
          }}
        />
        <div className="absolute left-1/2 top-0 h-3 w-px bg-slate-600" />
      </div>
      <div
        className={`w-16 text-right font-mono ${
          pos ? "text-red-400" : "text-emerald-400"
        }`}
      >
        {shap >= 0 ? "+" : ""}
        {shap.toFixed(3)}
      </div>
    </div>
  );
}