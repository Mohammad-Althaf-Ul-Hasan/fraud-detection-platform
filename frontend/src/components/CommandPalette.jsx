import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Command } from "cmdk";
import { toast } from "sonner";
import { endpoints } from "@/api";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  GitBranch,
  RefreshCw,
  Search,
  Workflow,
} from "lucide-react";

const PAGES = [
  { label: "Live Alerts",      to: "/alerts",  icon: AlertTriangle, shortcut: "G A" },
  { label: "Metrics",          to: "/metrics", icon: BarChart3,     shortcut: "G M" },
  { label: "Graph Explorer",   to: "/graph",   icon: GitBranch,     shortcut: "G G" },
  { label: "Model Versions",   to: "/models",  icon: Workflow,      shortcut: "G V" },
  { label: "Drift Monitor",    to: "/drift",   icon: Activity,      shortcut: "G D" },
];

export default function CommandPalette({ open, onOpenChange }) {
  const navigate = useNavigate();
  const [recent, setRecent] = useState([]);

  useEffect(() => {
    if (!open) return;
    endpoints
      .recent(20)
      .then((r) => {
        const items = Array.isArray(r) ? r : r.value || [];
        setRecent(items);
      })
      .catch(() => setRecent([]));
  }, [open]);

  function go(to) {
    onOpenChange(false);
    navigate(to);
  }

  async function handleReloadModel() {
    onOpenChange(false);
    try {
      const res = await endpoints.reload();
      toast.success("Model reloaded", {
        description: `run ${res.current_run_id?.slice(0, 8)} · thr ${res.threshold?.toFixed(4)}`,
      });
    } catch (e) {
      toast.error("Reload failed", { description: e.message });
    }
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command palette"
      className="cmdk-dialog"
    >
      <div className="cmdk-panel">
        <Command.Input placeholder="Type a command, page, or txn id…" className="cmdk-input" />
        <Command.List className="cmdk-list">
          <Command.Empty className="cmdk-empty">
            <Search className="mx-auto mb-2 h-4 w-4 opacity-40" />
            No results.
          </Command.Empty>

          <Command.Group heading="Pages" className="cmdk-group">
            {PAGES.map((p) => {
              const Icon = p.icon;
              return (
                <Command.Item
                  key={p.to}
                  onSelect={() => go(p.to)}
                  className="cmdk-item"
                >
                  <Icon className="h-3.5 w-3.5 opacity-70" />
                  <span>{p.label}</span>
                  <span className="cmdk-shortcut">{p.shortcut}</span>
                </Command.Item>
              );
            })}
          </Command.Group>

          <Command.Group heading="Actions" className="cmdk-group">
            <Command.Item
              onSelect={handleReloadModel}
              className="cmdk-item"
            >
              <RefreshCw className="h-3.5 w-3.5 opacity-70" />
              <span>Reload latest model</span>
              <span className="cmdk-shortcut">POST</span>
            </Command.Item>
            <Command.Item
              onSelect={() => go("/drift")}
              className="cmdk-item"
            >
              <Activity className="h-3.5 w-3.5 opacity-70" />
              <span>Open drift report</span>
              <ArrowRight className="ml-auto h-3 w-3 opacity-40" />
            </Command.Item>
          </Command.Group>

          {recent.length > 0 && (
            <Command.Group heading="Recent cases" className="cmdk-group">
              {recent.slice(0, 8).map((t) => (
                <Command.Item
                  key={t.txn_id}
                  value={`case ${t.txn_id} ${t.nameOrig} ${t.nameDest}`}
                  onSelect={() => go(`/case/${t.txn_id}`)}
                  className="cmdk-item"
                >
                  <span className="font-mono text-[11px] text-muted-foreground w-12 shrink-0">
                    {t.txn_id}
                  </span>
                  <span className="font-mono text-[11px] truncate">{t.nameOrig}</span>
                  <span
                    className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      t.decision === "BLOCK"
                        ? "bg-red-500/15 text-red-400"
                        : "bg-emerald-500/10 text-emerald-400"
                    }`}
                  >
                    {t.decision}
                  </span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
        </Command.List>
      </div>
    </Command.Dialog>
  );
}