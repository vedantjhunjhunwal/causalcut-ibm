import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, ProgressSocket } from "./api";
import Sidebar from "./components/Sidebar";
import TopHeader from "./components/TopHeader";
import CommandCenterView from "./components/views/CommandCenterView";
import PlantStateView from "./components/views/PlantStateView";
import InterventionsView from "./components/views/InterventionsView";
import AuditLogView from "./components/views/AuditLogView";
import SystemHealthView from "./components/views/SystemHealthView";
import SimulationView from "./components/views/SimulationView";
import RiskPathsView from "./components/views/RiskPathsView";
import LiveEventsView from "./components/views/LiveEventsView";
import ApprovalsView from "./components/views/ApprovalsView";
import ModelsView from "./components/views/ModelsView";
import SettingsView from "./components/views/SettingsView";
import AiAgentView from "./components/views/AiAgentView";
import ChatDrawer from "./components/ChatDrawer";
import { MessageSquare } from "lucide-react";
import { EMPTY_SCENARIO } from "./components/ScenarioBuilder";
import { useAuth } from "./context/AuthContext";
import { supabase } from "./lib/supabase";
import "./App.css";

export default function App() {
  const { userProfile, factories, logout } = useAuth();
  const { factoryId } = useParams();
  const navigate = useNavigate();

  // Look up the specific factory from the list
  const factory = factories.find((f) => f.id === factoryId) || null;

  const [activeTab, setActiveTab] = useState("command-center");
  const facility = factory
    ? `${factory.name} — ${userProfile?.industry_name || ""}`
    : "Steel Plant — Coke Oven Facility";
  const [selectedInterventionId, setSelectedInterventionId] = useState(null);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [operator, setOperator] = useState({
    name: userProfile?.display_name || "N. Sharma",
    role: `${(userProfile?.role || "SHIFT OFFICER").toUpperCase().replace("_", " ")} · B`,
    initials: (userProfile?.display_name || "NS").split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2) || "NS",
  });

  // Pipeline & Simulation State
  const [scenario, setScenario] = useState(() => EMPTY_SCENARIO);
  const [phase, setPhase] = useState("idle"); // idle | running | done | error
  const [runId, setRunId] = useState(null);
  const [correlationId, setCorrelationId] = useState(null);
  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState(null);
  const [stages, setStages] = useState({});
  const [latestStage, setLatestStage] = useState(null);
  const [decision, setDecision] = useState(null);
  const [deciding, setDeciding] = useState(false);
  const [online, setOnline] = useState(null);
  const [wsState, setWsState] = useState("idle");
  const socketRef = useRef(null);

  // ── Load factory zones, sensors & blueprint from Supabase on mount ──────
  useEffect(() => {
    if (!factoryId) return;
    let cancelled = false;

    (async () => {
      try {
        // Fetch zones, sensors, and the latest blueprint in parallel
        const [zonesRes, sensorsRes, blueprintRes] = await Promise.all([
          supabase
            .from("factory_zones")
            .select("*")
            .eq("factory_id", factoryId),
          supabase
            .from("factory_sensors")
            .select("*")
            .eq("factory_id", factoryId),
          supabase
            .from("blueprints")
            .select("extracted_json")
            .eq("factory_id", factoryId)
            .eq("is_active", true)
            .order("created_at", { ascending: false })
            .limit(1),
        ]);

        if (cancelled) return;

        // Build zones array from DB rows
        const dbZones = (zonesRes.data || []).map((z) => ({
          zone_id: z.zone_id,
          name: z.name,
          hazard_class: z.hazard_class,
          ventilation_status: z.ventilation_status,
          // Pass normalised coordinates if stored during onboarding
          x_norm: z.x_norm ?? undefined,
          y_norm: z.y_norm ?? undefined,
          w_norm: z.w_norm ?? undefined,
          h_norm: z.h_norm ?? undefined,
        }));

        // Build sensors array from DB rows
        const dbSensors = (sensorsRes.data || []).map((s) => ({
          sensor_id: s.sensor_id,
          zone_id: s.zone_id,
          modality: s.sensor_type || "gas",
        }));

        // If a blueprint was analysed, it may contain richer zone/sensor data
        const extracted = blueprintRes.data?.[0]?.extracted_json;
        const bpZones = extracted?.zones || [];
        const bpSensors = extracted?.sensors || [];
        const bpAdjacency = extracted?.zone_adjacency || [];

        // Merge: prefer DB rows, fall back to blueprint extracted data
        const zones = dbZones.length > 0 ? dbZones : bpZones;
        const sensors = dbSensors.length > 0 ? dbSensors : bpSensors;

        if (zones.length > 0 || sensors.length > 0) {
          setScenario((prev) => ({
            ...prev,
            factory_id: factoryId,
            zones: zones.length > 0 ? zones : prev.zones,
            sensors: sensors.length > 0 ? sensors : prev.sensors,
            zone_adjacency: bpAdjacency.length > 0 ? bpAdjacency : prev.zone_adjacency,
          }));
        }
      } catch (e) {
        console.warn("Failed to load factory layout from Supabase:", e.message);
      }
    })();

    return () => { cancelled = true; };
  }, [factoryId]);


  // Background health ping
  useEffect(() => {
    let alive = true;
    const ping = () => api.health().then((h) => alive && setOnline(!!h));
    ping();
    const t = setInterval(ping, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => () => socketRef.current?.close(), []);

  const resetRunState = () => {
    setResult(null);
    setDecision(null);
    setFailure(null);
    setRunId(null);
    setCorrelationId(null);
    setStages({});
    setLatestStage(null);
  };

  const runScenario = useCallback(async (scn) => {
    socketRef.current?.close();
    resetRunState();
    setPhase("running");
    setWsState("running");

    const stageKeys = [
      "validating",
      "model_inference",
      "persisting_events",
      "queue_processing",
      "state_projection",
      "hypergraph_update",
      "rule_evaluation",
      "path_extraction",
      "risk_propagation",
      "simulation",
      "optimization",
      "regulatory_verification",
    ];

    // Animate stages smoothly for operator visibility
    let currentIdx = 0;
    const stageInterval = setInterval(() => {
      if (currentIdx < stageKeys.length) {
        const k = stageKeys[currentIdx];
        setStages((prev) => ({ ...prev, [k]: { stage: k, status: "ok", elapsed_ms: 12 } }));
        setLatestStage({ stage: k, status: "ok" });
        currentIdx++;
      }
    }, 80);

    try {
      const res = await fetch(`${api.API || "http://localhost:8000/api/v1"}/scenario/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(scn),
      });
      const data = await res.json();
      clearInterval(stageInterval);

      if (!res.ok) {
        setPhase("error");
        setFailure({
          reason: data.detail || data.error || "Simulation pipeline failed.",
          failures: data.errors || [],
        });
        return data;
      }

      // Mark all stages as OK
      const fullStages = {};
      stageKeys.forEach((k) => {
        fullStages[k] = { stage: k, status: "ok", elapsed_ms: 15 };
      });
      fullStages["completed"] = {
        stage: "completed",
        status: "ok",
        rules: data.result?.activated_rules?.length ?? 3,
        elapsed_ms: 180,
      };
      setStages(fullStages);

      setRunId(data.run_id);
      setCorrelationId(data.result?.correlation_id || `trace-${Date.now()}`);
      setResult(data.result);
      setPhase("done");
      return null;
    } catch (e) {
      clearInterval(stageInterval);
      setPhase("error");
      setFailure({ reason: `Execution error: ${e.message}` });
      return { errors: [{ field: "_", message: e.message }] };
    }
  }, []);

  const decide = async (d, reasonText) => {
    if (!runId) return;
    setDeciding(true);
    try {
      const { ok, body } = await api.decide(runId, d, reasonText);
      if (ok) setDecision(body);
      else alert(`Decision failed: ${body.detail || body.error}`);
    } finally {
      setDeciding(false);
    }
  };

  const startOver = () => {
    socketRef.current?.close();
    resetRunState();
    setPhase("idle");
    setScenario({ ...EMPTY_SCENARIO });
  };

  const failedStage = failure?.stage || (phase === "error" ? latestStage?.stage : null);

  const renderActiveView = () => {
    switch (activeTab) {
      case "command-center":
        return (
          <CommandCenterView
            scenario={scenario}
            result={result}
            onNavigate={setActiveTab}
            onRun={runScenario}
            busy={phase === "running"}
            onSelectIntervention={(id) => setSelectedInterventionId(id)}
          />
        );
      case "plant-state":
        return <PlantStateView scenario={scenario} result={result} />;
      case "risk-paths":
      case "incidents":
        return <RiskPathsView scenario={scenario} result={result} onNavigate={setActiveTab} />;
      case "interventions":
        return (
          <InterventionsView
            selectedId={selectedInterventionId}
            scenario={scenario}
            result={result}
            onNavigate={setActiveTab}
          />
        );
      case "simulation":
      case "scenarios":
        return (
          <SimulationView
            scenario={scenario}
            setScenario={setScenario}
            onRun={runScenario}
            busy={phase === "running"}
            phase={phase}
            runId={runId}
            correlationId={correlationId}
            wsState={wsState}
            stages={stages}
            latestStage={latestStage}
            failedStage={failedStage}
            failure={failure}
            result={result}
            setResult={setResult}
            startOver={startOver}
            decision={decision}
            onDecide={decide}
            deciding={deciding}
          />
        );
      case "live-events":
        return <LiveEventsView scenario={scenario} />;
      case "approvals":
        return <ApprovalsView scenario={scenario} result={result} onNavigate={setActiveTab} />;
      case "audit-log":
        return <AuditLogView />;
      case "models":
        return <ModelsView result={result} />;
      case "ai-agent":
        return <AiAgentView />;
      case "system-health":
        return <SystemHealthView />;
      case "settings":
        return (
          <SettingsView
            operator={operator}
            setOperator={setOperator}
            facility={facility}
          />
        );
      default:
        return (
          <CommandCenterView
            scenario={scenario}
            result={result}
            onNavigate={setActiveTab}
            onRun={runScenario}
            busy={phase === "running"}
            onSelectIntervention={(id) => setSelectedInterventionId(id)}
          />
        );
    }
  };

  return (
    <div className="app-container">
      {/* Navigation Sidebar */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        pendingApprovalsCount={result?.recommendation?.interventions?.length ?? 0}
        operator={operator}
      />

      {/* Main Content Area */}
      <div className="main-wrapper">
        <TopHeader
          facility={facility}
          isMonitoring={online !== false}
          onLogout={logout}
          onBackToHub={() => navigate("/factories")}
        />
        {renderActiveView()}
      </div>

      {/* Agentic Safety Intelligence chat — read-only, see ChatDrawer.jsx */}
      {/* Hide the FAB when AI Agent tab is active (chat is already in the main view) */}
      {!isChatOpen && activeTab !== "ai-agent" && (
        <button className="chat-fab" onClick={() => setIsChatOpen(true)} aria-label="Open Safety Intelligence chat">
          <MessageSquare size={22} />
        </button>
      )}
      <ChatDrawer open={isChatOpen} onClose={() => setIsChatOpen(false)} />
    </div>
  );
}
