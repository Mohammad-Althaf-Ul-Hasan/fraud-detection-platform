import { useEffect, useRef, useState } from "react";
import { AlertCircle, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export default function NarrativeCard({ txn }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const [remaining, setRemaining] = useState(null);
  const abortRef = useRef(null);

  async function load(regenerate = false) {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setText("");
    setError(null);
    setDone(false);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/explain/narrative`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ txn_id: txn.txn_id, regenerate }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const msg = await res.text().catch(() => "");
        throw new Error(`${res.status}: ${msg.slice(0, 160)}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done: rDone, value } = await reader.read();
        if (rDone) break;
        buffer += decoder.decode(value, { stream: true });

        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const dataLine = frame
            .split("\n")
            .find((l) => l.startsWith("data: "));
          if (!dataLine) continue;
          try {
            const data = JSON.parse(dataLine.slice(6));
            if (data.text) setText((t) => t + data.text);
            if (data.done) {
              setDone(true);
              if (typeof data.remaining_today === "number") {
                setRemaining(data.remaining_today);
              }
            }
            if (data.error) setError(data.error);
          } catch {
            /* malformed frame — skip */
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(false);
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [txn.txn_id]);

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-violet-400" />
          <h2 className="text-sm font-semibold">Analyst narrative</h2>
          {done && !error && (
            <span className="text-[10px] text-muted-foreground">
              AI-generated
            </span>
          )}
          {remaining !== null && (
            <span className="text-[10px] text-muted-foreground">
              · {remaining} today
            </span>
          )}
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => load(true)}
          disabled={loading}
          className="h-6 px-2 text-[10px]"
        >
          <RefreshCw
            className={`h-3 w-3 mr-1 ${loading ? "animate-spin" : ""}`}
          />
          Regenerate
        </Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/5 border border-red-500/20 rounded p-2">
          <AlertCircle className="h-3 w-3 mt-0.5 shrink-0" />
          <span className="break-words">{error}</span>
        </div>
      )}

      {!text && loading && (
        <div className="space-y-2">
          <div className="h-3 w-full bg-muted/30 rounded animate-pulse" />
          <div className="h-3 w-5/6 bg-muted/30 rounded animate-pulse" />
          <div className="h-3 w-4/6 bg-muted/30 rounded animate-pulse" />
        </div>
      )}

      {text && (
        <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">
          {text}
          {!done && loading && (
            <span className="inline-block w-1.5 h-4 ml-0.5 bg-violet-400 animate-pulse align-middle" />
          )}
        </p>
      )}
    </Card>
  );
}