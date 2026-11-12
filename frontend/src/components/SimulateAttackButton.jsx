import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { endpoints } from "@/api";
import { Button } from "@/components/ui/button";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

export default function SimulateAttackButton() {
  const navigate = useNavigate();
  const [state, setState] = useState("idle");   // idle | running | done
  const [result, setResult] = useState(null);

  async function launch() {
    setState("running");
    try {
      const res = await endpoints.simulateAttack();
      setResult(res);
      toast.success("Fraud ring attack launched", {
        description: `5 accounts · shared device ${res.device_id.slice(-8)} · watch alerts`,
        duration: 6000,
      });
      setTimeout(() => setState("done"), 2500);
    } catch (e) {
      setState("idle");
      toast.error("Attack failed", { description: e.message });
    }
  }

  if (state === "done" && result) {
    return (
      <Button
        size="sm"
        variant="outline"
        onClick={() => navigate(`/graph?account=${result.accounts[0]}`)}
        className="border-violet-500/40 bg-violet-500/5 text-violet-300 hover:bg-violet-500/15 hover:border-violet-500/60"
        title={`Ring ${result.ring_id} · click to view in Graph Explorer`}
      >
        <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
        Ring caught · view graph
      </Button>
    );
  }

  return (
    <Button
      size="sm"
      onClick={launch}
      disabled={state === "running"}
      className={
        state === "running"
          ? "bg-red-600/40 text-red-300"
          : "bg-red-600 hover:bg-red-500 text-white"
      }
      title="Inject 5 coordinated fraud accounts into the live stream"
    >
      {state === "running" ? (
        <>
          <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
          Injecting attack...
        </>
      ) : (
        <>
          <AlertTriangle className="h-3.5 w-3.5 mr-1.5" />
          Simulate fraud ring attack
        </>
      )}
    </Button>
  );
}