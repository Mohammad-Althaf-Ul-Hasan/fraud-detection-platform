import { useEffect, useState } from "react";
import { Circle } from "lucide-react";

/**
 * Pulsing status indicator. Not only shows connected/disconnected but
 * also pulses when a fresh event arrives (via `pulseKey` prop).
 */
export default function LiveHeartbeat({ connected, pulseKey = 0, label = "Live" }) {
  const [pulsing, setPulsing] = useState(false);

  useEffect(() => {
    if (!pulseKey) return;
    setPulsing(true);
    const t = setTimeout(() => setPulsing(false), 900);
    return () => clearTimeout(t);
  }, [pulseKey]);

  const color = connected ? "text-emerald-500" : "text-red-500";

  return (
    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span className="relative flex h-2 w-2">
        {connected && (
          <span
            className={`absolute inline-flex h-full w-full rounded-full bg-emerald-400 ${
              pulsing ? "animate-ping opacity-75" : "opacity-0"
            }`}
          />
        )}
        <Circle className={`relative h-2 w-2 fill-current ${color}`} />
      </span>
      {connected ? label : "Reconnecting"}
    </div>
  );
}