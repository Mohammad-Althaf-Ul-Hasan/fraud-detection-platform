import { cn } from "@/lib/utils";

export default function Slider({
  value, onChange, min, max, step = 1, label, formatValue, className,
}) {
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
          {label}
        </span>
        <span className="font-mono text-xs tabular-nums text-foreground">
          {formatValue ? formatValue(value) : value}
        </span>
      </div>
      <div className="relative h-1.5 rounded-full bg-muted/50">
        <div
          className="absolute top-0 left-0 h-full rounded-full bg-gradient-to-r from-violet-500 to-violet-400"
          style={{ width: `${pct}%` }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="slider-input absolute inset-0 w-full cursor-pointer appearance-none bg-transparent"
        />
      </div>
    </div>
  );
}