import { NavLink, useLocation } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  GitBranch,
  Shield,
  Users,
  Workflow,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const NAV = [
  {
    label: "Monitor",
    items: [
      { to: "/alerts",  icon: AlertTriangle, label: "Live Alerts",    dot: "live" },
      { to: "/metrics", icon: BarChart3,     label: "Metrics",        dot: "data" },
    ],
  },
  {
    label: "Investigate",
    items: [
      { to: "/graph",   icon: GitBranch,     label: "Graph Explorer", dot: "rings" },
      { to: "/rings",   icon: Users,         label: "Ring Discovery", dot: "rings" },
    ],
  },
  {
    label: "Operate",
    items: [
      { to: "/models",  icon: Workflow,      label: "Model Versions", dot: "model" },
      { to: "/drift",   icon: Activity,      label: "Drift Monitor",  dot: "drift" },
    ],
  },
];

const DOT_STYLES = {
  live:  { color: "bg-emerald-500 shadow-[0_0_6px] shadow-emerald-500/60", label: "streaming" },
  data:  { color: "bg-emerald-500 shadow-[0_0_6px] shadow-emerald-500/60", label: "healthy" },
  rings: { color: "bg-violet-500 shadow-[0_0_6px] shadow-violet-500/60",   label: "8 rings" },
  model: { color: "bg-emerald-500 shadow-[0_0_6px] shadow-emerald-500/60", label: "loaded" },
  drift: { color: "bg-amber-500 shadow-[0_0_6px] shadow-amber-500/60",     label: "retrain" },
};

export default function AppSidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 ease-out",
        collapsed ? "w-[56px]" : "w-[232px]"
      )}
    >
      <div className="flex h-14 items-center gap-2.5 px-3 border-b border-sidebar-border">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-violet-500 to-violet-700 text-white shadow-[0_0_16px_-4px] shadow-violet-500/50">
          <Shield className="h-3.5 w-3.5" />
        </div>
        {!collapsed && (
          <div className="flex flex-col leading-none">
            <span className="text-[13px] font-semibold tracking-tight">Fraud Ops</span>
            <span className="text-[10px] text-muted-foreground">Detection Platform</span>
          </div>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {NAV.map((group) => (
          <div key={group.label}>
            {!collapsed && (
              <div className="px-2 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/80">
                {group.label}
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map(({ to, icon: Icon, label, dot }) => {
                const active = location.pathname.startsWith(to);
                const dotStyle = DOT_STYLES[dot];
                const item = (
                  <NavLink
                    key={to}
                    to={to}
                    className={cn(
                      "group flex items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] transition-colors",
                      active
                        ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                        : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                      collapsed && "justify-center px-0"
                    )}
                  >
                    <Icon
                      className={cn(
                        "h-4 w-4 shrink-0",
                        active ? "text-violet-400" : ""
                      )}
                    />
                    {!collapsed && (
                      <>
                        <span className="truncate">{label}</span>
                        {dotStyle && (
                          <span
                            className={cn(
                              "ml-auto h-1.5 w-1.5 rounded-full",
                              dotStyle.color
                            )}
                            title={dotStyle.label}
                          />
                        )}
                      </>
                    )}
                  </NavLink>
                );
                return collapsed ? (
                  <Tooltip key={to}>
                    <TooltipTrigger asChild>{item}</TooltipTrigger>
                    <TooltipContent side="right">{label}</TooltipContent>
                  </Tooltip>
                ) : (
                  item
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <Separator />
      <div className="p-2">
        <Button
          variant="ghost"
          size="sm"
          className={cn("w-full h-8", collapsed ? "px-0" : "justify-start")}
          onClick={() => setCollapsed((v) => !v)}
        >
          {collapsed ? (
            <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <ChevronLeft className="h-3.5 w-3.5" />
          )}
          {!collapsed && (
            <span className="ml-2 text-[11px] text-muted-foreground">Collapse</span>
          )}
        </Button>
      </div>
    </aside>
  );
}