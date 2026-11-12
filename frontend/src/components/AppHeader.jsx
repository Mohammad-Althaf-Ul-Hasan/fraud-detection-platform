import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { endpoints } from "@/api";
import { useDensity } from "./DensityProvider";
import LiveHeartbeat from "./LiveHeartbeat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AlignVerticalSpaceAround,
  Command,
  Maximize2,
  Minimize2,
  Search,
} from "lucide-react";

function DensityMenu({ density, setDensity }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const opts = [
    { key: "compact",     label: "Compact",     icon: Minimize2 },
    { key: "comfortable", label: "Comfortable", icon: AlignVerticalSpaceAround },
    { key: "relaxed",     label: "Relaxed",     icon: Maximize2 },
  ];

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        onClick={() => setOpen((v) => !v)}
      >
        <AlignVerticalSpaceAround className="h-3.5 w-3.5" />
      </Button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-md border border-border bg-popover p-1 shadow-xl">
          <div className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
            Density
          </div>
          <div className="my-1 h-px bg-border" />
          {opts.map((opt) => {
            const Icon = opt.icon;
            return (
              <button
                key={opt.key}
                onClick={() => {
                  setDensity(opt.key);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/60"
              >
                <Icon className="h-3 w-3 opacity-60" />
                <span>{opt.label}</span>
                {density === opt.key && (
                  <span className="ml-auto h-1.5 w-1.5 rounded-full bg-violet-500" />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function AppHeader({
  health,
  alertCount = 0,
  pulseKey = 0,
  onOpenCommandPalette,
}) {
  const navigate = useNavigate();
  const { density, setDensity } = useDensity();
  const [q, setQ] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    function handler(e) {
      const t = e.target;
      const typing =
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable);
      if (!typing && e.key === "/") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    const query = q.trim();
    if (!query) return;
    try {
      const recents = await endpoints.recent(500);
      const items = Array.isArray(recents) ? recents : recents.value || [];
      const match = items.find(
        (t) =>
          t.txn_id === query ||
          t.nameOrig === query ||
          t.nameDest === query
      );
      if (match) {
        setQ("");
        if (match.txn_id === query) navigate(`/case/${match.txn_id}`);
        else navigate(`/alerts?q=${encodeURIComponent(match.nameOrig)}`);
        return;
      }
    } catch {
      /* ignore */
    }
    setQ("");
    navigate(`/alerts?q=${encodeURIComponent(query)}`);
  }

  return (
    <header className="flex h-14 items-center gap-4 border-b border-border bg-background/70 px-6 backdrop-blur-md">
      <form onSubmit={handleSubmit} className="flex-1 max-w-md">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={inputRef}
            placeholder="Search txn, account, or destination…"
            className="h-8 pl-8 pr-12 text-sm bg-card/50 border-border/60 focus-visible:bg-card"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <kbd className="cmd-k absolute right-1.5 top-1/2 -translate-y-1/2">
            /
          </kbd>
        </div>
      </form>

      <button
        onClick={onOpenCommandPalette}
        className="hidden md:flex items-center gap-2 rounded-md border border-border/60 bg-card/40 px-2 py-1.5 text-xs text-muted-foreground hover:bg-card hover:border-border transition-colors"
      >
        <Command className="h-3 w-3" />
        <span className="text-[11px]">Quick actions</span>
        <kbd className="cmd-k">⌘K</kbd>
      </button>

      <div className="flex items-center gap-2">
        {alertCount > 0 && (
          <Badge variant="destructive" className="text-[10px] animate-in fade-in">
            {alertCount} new
          </Badge>
        )}

        <LiveHeartbeat
          connected={health?.status === "ok"}
          pulseKey={pulseKey}
        />

        <DensityMenu density={density} setDensity={setDensity} />

        <Badge variant="outline" className="text-[10px] font-mono h-6">
          {health?.model_run_id?.slice(0, 8) ?? "—"}
        </Badge>
      </div>
    </header>
  );
}