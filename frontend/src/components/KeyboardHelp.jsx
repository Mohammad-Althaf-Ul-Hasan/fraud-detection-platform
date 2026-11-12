import { useEffect } from "react";
import { SHORTCUT_GROUPS } from "@/lib/shortcuts";

export default function KeyboardHelp({ open, onOpenChange }) {
  useEffect(() => {
    if (!open) return;
    function handler(e) {
      if (e.key === "Escape") onOpenChange(false);
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onOpenChange]);

  if (!open) return null;

  return (
    <div
      className="cmdk-dialog"
      onClick={(e) => {
        if (e.target === e.currentTarget) onOpenChange(false);
      }}
    >
      <div
        className="cmdk-panel max-w-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold">Keyboard shortcuts</h2>
        </div>
        <div className="max-h-[70vh] space-y-5 overflow-y-auto p-5">
          {SHORTCUT_GROUPS.map((group) => (
            <div key={group.name}>
              <h3 className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
                {group.name}
              </h3>
              <div className="space-y-1">
                {group.shortcuts.map((s) => (
                  <div
                    key={s.keys}
                    className="flex items-center justify-between rounded px-2 py-1.5 hover:bg-muted/40"
                  >
                    <span className="text-sm text-foreground/90">
                      {s.description}
                    </span>
                    <kbd className="cmd-k">{s.keys}</kbd>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}