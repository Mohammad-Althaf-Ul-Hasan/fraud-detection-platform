import { Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { DensityProvider } from "@/components/DensityProvider";
import Layout from "./components/Layout";
import LiveAlerts from "./pages/LiveAlerts";
import CaseDetail from "./pages/CaseDetail";
import Metrics from "./pages/Metrics";
import GraphView from "./pages/GraphView";
import ModelVersions from "./pages/ModelVersions";
import DriftMonitor from "./pages/DriftMonitor";
import Rings from "./pages/Rings";

export default function App() {
  return (
    <DensityProvider>
      <TooltipProvider delayDuration={150}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/alerts" replace />} />
            <Route path="/alerts" element={<LiveAlerts />} />
            <Route path="/case/:txnId" element={<CaseDetail />} />
            <Route path="/metrics" element={<Metrics />} />
            <Route path="/graph" element={<GraphView />} />
            <Route path="/models" element={<ModelVersions />} />
            <Route path="/drift" element={<DriftMonitor />} />
            <Route path="/rings" element={<Rings />} />
          </Route>
        </Routes>
        <Toaster
          theme="dark"
          position="bottom-right"
          richColors
          closeButton
          toastOptions={{
            classNames: {
              toast: "border border-border shadow-xl",
              title: "text-sm font-medium",
              description: "text-xs text-muted-foreground",
            },
          }}
        />
      </TooltipProvider>
    </DensityProvider>
  );
}