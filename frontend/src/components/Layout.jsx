import { useEffect, useMemo, useRef, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import AppSidebar from "./AppSidebar";
import AppHeader from "./AppHeader";
import CommandPalette from "./CommandPalette";
import KeyboardHelp from "./KeyboardHelp";
import { endpoints } from "@/api";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";

export default function Layout() {
  const navigate = useNavigate();
  const [health, setHealth] = useState(null);
  const [alertCount, setAlertCount] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [pulseKey, setPulseKey] = useState(0);
  const prevBlockRef = useRef(0);

  // Poll health every 5s
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const [h, s] = await Promise.all([endpoints.health(), endpoints.stats()]);
        if (cancelled) return;
        setHealth(h);
        const blocked = s?.counters?.predicted_fraud ?? 0;
        if (blocked > prevBlockRef.current) {
          setAlertCount((c) => c + (blocked - prevBlockRef.current));
          setPulseKey((k) => k + 1);
        }
        prevBlockRef.current = blocked;
      } catch {
        /* keep last known */
      }
    }
    poll();
    const t = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  // Clear alert count when user visits Live Alerts
  useEffect(() => {
    if (window.location.pathname.startsWith("/alerts")) {
      setAlertCount(0);
    }
  }, [window.location.pathname]);

  // Cmd/Ctrl+K opens command palette
  useEffect(() => {
    function handler(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
      if (e.key === "Escape") {
        setPaletteOpen(false);
        setHelpOpen(false);
      }
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const shortcuts = useMemo(
    () => ({
      "g a": () => navigate("/alerts"),
      "g m": () => navigate("/metrics"),
      "g g": () => navigate("/graph"),
      "g v": () => navigate("/models"),
      "g d": () => navigate("/drift"),
      "?": () => setHelpOpen((v) => !v),
    }),
    [navigate]
  );

  useKeyboardShortcuts(shortcuts);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <AppSidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <AppHeader
          health={health}
          alertCount={alertCount}
          pulseKey={pulseKey}
          onOpenCommandPalette={() => setPaletteOpen(true)}
        />
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <KeyboardHelp open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  );
}