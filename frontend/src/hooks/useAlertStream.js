import { useEffect, useRef, useState } from "react";
import { WS_BASE } from "@/api";

export function useAlertStream(maxAlerts = 200) {
  const [connected, setConnected] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const wsRef = useRef(null);
  const retryRef = useRef(0);
  const timerRef = useRef(null);
  const stoppedRef = useRef(false);

  useEffect(() => {
    stoppedRef.current = false;

    function connect() {
      if (stoppedRef.current) return;
      const url = `${WS_BASE}/ws/alerts`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        retryRef.current = 0;
        setConnected(true);
      };

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          setAlerts((prev) => {
            if (prev[0]?.txn_id === data.txn_id) return prev;
            return [data, ...prev].slice(0, maxAlerts);
          });
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        setConnected(false);
        if (stoppedRef.current) return;
        const delay = Math.min(1000 * 2 ** retryRef.current, 10000);
        retryRef.current += 1;
        timerRef.current = setTimeout(connect, delay);
      };

      ws.onerror = () => { try { ws.close(); } catch { /* noop */ } };
    }

    connect();

    return () => {
      stoppedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      try { wsRef.current?.close(); } catch { /* noop */ }
    };
  }, [maxAlerts]);

  return { connected, alerts };
}