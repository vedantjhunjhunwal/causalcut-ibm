import { useCallback, useEffect, useRef, useState } from "react";
import { api, ProgressSocket } from "./api";
import ScenarioBuilder, { EMPTY_SCENARIO } from "./components/ScenarioBuilder";
import ExecutionStatus from "./components/ExecutionStatus";
import ResultsDashboard from "./components/ResultsDashboard";
import ModelStatus from "./components/ModelStatus";
import ModelInputPanel from "./components/ModelInputPanel";
import "./App.css";

export default function App() {
  // Deliberately empty on load: no scenario is auto-selected, auto-loaded or
  // auto-executed. The pipeline only runs when the operator clicks Run Scenario.
  const [scenario, setScenario] = useState({ ...EMPTY_SCENARIO });
  const [phase, setPhase] = useState("idle"); // idle | running | done | error
  const [runId, setRunId] = useState(null);
  const [correlationId, setCorrelationId] = useState(null);
  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState(null);
  // Real backend stages, keyed by stage name. Nothing is inserted here that
  // the pipeline did not actually emit.
  const [stages, setStages] = useState({});
  const [latestStage, setLatestStage] = useState(null);
  const [decision, setDecision] = useState(null);
  const [deciding, setDeciding] = useState(false);
  const [online, setOnline] = useState(null);
  const [wsState, setWsState] = useState("idle");
  const socketRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const ping = () => api.health().then((h) => alive && setOnline(!!h));
    ping();
    const t = setInterval(ping, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // Never leave a socket dangling if the operator navigates away mid-run.
  useEffect(() => () => socketRef.current?.close(), []);

  const resetRunState = () => {
    setResult(null); setDecision(null); setFailure(null);
    setRunId(null); setCorrelationId(null);
    setStages({}); setLatestStage(null);
  };

  /**
   * Asynchronous execution.
   *
   *   POST /scenario/start        -> 202 + run_id, immediately
   *   ws  /ws/scenarios/{run_id}  -> real pipeline stages as they happen
   *   GET /scenario/runs/{run_id} -> authoritative final result
   *
   * The socket stays open for the whole run and is only closed once the
   * backend reports completion or failure. If it drops, ProgressSocket
   * reconnects (the server replays the stages we missed) and polls the run
   * endpoint in the meantime.
   */
  const runScenario = useCallback(async (scn) => {
    socketRef.current?.close();
    resetRunState();
    setPhase("running");
    setWsState("connecting");

    let started;
    try {
      started = await api.start(scn);
    } catch (e) {
      setPhase("error");
      setFailure({ reason: `Could not reach the backend: ${e.message}` });
      return { errors: [{ field: "_", message: e.message }] };
    }

    if (!started.ok) {
      // 422 from schema validation — hand the field errors back to the builder.
      setPhase("error");
      setWsState("idle");
      if (!started.body?.errors) {
        setFailure({ reason: started.body?.detail || started.body?.error ||
                             `Run rejected (HTTP ${started.status}).` });
      }
      return started.body;
    }

    const { run_id, correlation_id } = started.body;
    setRunId(run_id);
    setCorrelationId(correlation_id ?? null);

    const sock = new ProgressSocket({
      onStage: (msg) => {
        setStages((prev) => {
          const prior = prev[msg.stage];
          // A stage can report "running" then "ok"; keep the latest, but never
          // let a stale message downgrade one that already finished.
          if (prior && prior.status === "ok" && msg.status === "running") return prev;
          return { ...prev, [msg.stage]: msg };
        });
        setLatestStage(msg);
      },
      onState: setWsState,
      onSettled: ({ status, result: finalResult }) => {
        if (status === "completed" && finalResult?.graph) {
          setResult(finalResult);
          setPhase("done");
        } else {
          // Fail-closed run: the backend suppressed analysis on incomplete
          // state, so there is no graph and no recommendation to show.
          setFailure({
            reason: finalResult?.failure_reason || "Pipeline did not complete.",
            stage: finalResult?.failure_stage,
            failures: finalResult?.failures || [],
            explanation: finalResult?.explanation,
            models: finalResult?.models,
          });
          setPhase("error");
        }
      },
      onError: (err) => {
        setFailure({ reason: err.message });
        setPhase("error");
      },
    });
    sock.subscribe(run_id);
    socketRef.current = sock;

    // Execution continues in the background; the builder is not blocked on it.
    return null;
  }, []);

  const decide = async (d, reason) => {
    if (!runId) return;
    setDeciding(true);
    try {
      const { ok, body } = await api.decide(runId, d, reason);
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

  return (
    <div className="app-shell">
      <header className="masthead">
        <div className="brand">
          <h1>CAUSAL<span className="tick">/</span>CUT</h1>
          <span className="sub">Minimum-Causal-Cut Safety Twin · Steelforge</span>
        </div>
        <span className="status-pill">
          <span className={`dot ${online ? "on" : "off"}`} />
          backend {online == null ? "…" : online ? "online" : "offline"} · ws {wsState}
        </span>
      </header>

      {!result ? (
        <div className="grid cols-2" style={{ gridTemplateColumns: "1.6fr 1fr", alignItems: "start" }}>
          <ScenarioBuilder scenario={scenario} setScenario={setScenario}
                           onRun={runScenario} busy={phase === "running"} />
          <div>
            {phase === "running" || phase === "error" ? (
              <div className="panel">
                <div className="panel-title">Run</div>
                <div className="mono" style={{ fontSize: 11, color: "var(--ink-dim)" }}>
                  {runId ? <>run <b>{runId}</b></> : "starting…"}
                  {correlationId && <> · correlation <b>{correlationId}</b></>}
                  <> · transport <b>{wsState}</b></>
                </div>
                {wsState === "polling" && (
                  <div className="warn" style={{ marginTop: 8 }}>
                    ⚠ Live socket unavailable — falling back to polling the run
                    endpoint. Stages below are still the backend's own; only the
                    update frequency is reduced.
                  </div>
                )}
              </div>
            ) : (
              <div className="panel">
                <div className="panel-title">Getting Started</div>
                <p className="hero-blurb">
                  No scenario is loaded. Build a factory incident on the left — add zones, sensors,
                  workers, permits and gas readings — or <span className="kbd">Upload JSON</span> /
                  load a sample. Attach camera frames and tracker detections from the
                  <span className="kbd">Raw Model Inputs</span> panel below and they run as part of
                  the scenario. Nothing runs until you press <span className="kbd">▶ Run Scenario</span>.
                </p>
              </div>
            )}

            <ExecutionStatus phase={phase} stages={stages} latest={latestStage}
                             failedStage={failedStage} />

            {failure && (
              <div className="panel">
                <div className="panel-title">Run Failed</div>
                <div className="err-msg">{failure.reason}</div>
                {failure.failures?.length > 0 && (
                  <ul className="dim" style={{ fontSize: 12, marginTop: 8, paddingLeft: 18 }}>
                    {failure.failures.map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                )}
                {failure.explanation && (
                  <p className="dim" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
                    {failure.explanation}
                  </p>
                )}
              </div>
            )}

            <ModelStatus />
            <ModelInputPanel scenario={scenario} setScenario={setScenario} />
          </div>
        </div>
      ) : (
        <div>
          <div className="btn-row" style={{ marginBottom: 16 }}>
            <button className="btn" onClick={() => { setResult(null); setPhase("idle"); }}>← Edit scenario</button>
            <button className="btn ghost" onClick={startOver}>New scenario</button>
            <span className="status-pill" style={{ marginLeft: "auto" }}>
              run <span className="mono">{runId}</span> · {result.scenario_name}
            </span>
          </div>
          <ResultsDashboard result={result} decision={decision} onDecide={decide} deciding={deciding} />
        </div>
      )}
    </div>
  );
}
