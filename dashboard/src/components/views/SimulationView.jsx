import React, { useState } from "react";
import ScenarioBuilder, { EMPTY_SCENARIO } from "../ScenarioBuilder";
import ExecutionStatus from "../ExecutionStatus";
import ResultsDashboard from "../ResultsDashboard";
import ModelStatus from "../ModelStatus";
import ModelInputPanel from "../ModelInputPanel";

export default function SimulationView({
  scenario,
  setScenario,
  onRun,
  busy,
  phase,
  runId,
  correlationId,
  wsState,
  stages,
  latestStage,
  failedStage,
  failure,
  result,
  setResult,
  startOver,
  decision,
  onDecide,
  deciding,
}) {
  return (
    <div className="page-canvas">
      {/* Header */}
      <div className="page-header">
        <div>
          <div className="breadcrumbs">COMMAND / SIMULATION & SCENARIOS</div>
          <h1 className="page-title">Digital Safety Twin Studio</h1>
          <div className="page-subtitle">
            Synthesize what-if industrial incidents, run ML models, and infer causal cuts.
          </div>
        </div>
        {result && (
          <div style={{ display: "flex", gap: 10 }}>
            <button className="action-btn" onClick={() => setResult(null)}>
              ← Edit scenario
            </button>
            <button className="action-btn primary" onClick={startOver}>
              + New scenario
            </button>
          </div>
        )}
      </div>

      {/* If result is available and user wants to view it */}
      {result ? (
        <ResultsDashboard
          result={result}
          scenario={scenario}
          runId={runId}
          correlationId={correlationId}
          decision={decision}
          onDecide={onDecide}
          deciding={deciding}
        />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 20, alignItems: "start" }}>
          {/* Left Column: Scenario Builder */}
          <ScenarioBuilder
            scenario={scenario}
            setScenario={setScenario}
            onRun={onRun}
            busy={busy}
          />

          {/* Right Column: Execution Status, Model Status, and Raw Inputs */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* Status card */}
            <div className="panel-box" style={{ padding: 16 }}>
              <div className="panel-header-row" style={{ marginBottom: 6 }}>
                <span className="panel-title-text">SIMULATION ENGINE</span>
                <span className="badge-pill connected">● ONLINE</span>
              </div>
              <p style={{ fontSize: 12, color: "#64748b", margin: 0, lineHeight: 1.45 }}>
                Configure zones, sensors, workers, and permits on the left, or upload a JSON incident scenario. Run the pipeline to trigger live ML inference, hypergraph propagation, and minimum causal cut optimization.
              </p>
            </div>

            {/* Execution Stages */}
            <ExecutionStatus
              phase={phase}
              stages={stages}
              latest={latestStage}
              failedStage={failedStage}
            />

            {/* Failure Alert if any */}
            {failure && (
              <div className="panel-box" style={{ padding: 16, backgroundColor: "#fef2f2", border: "1px solid #fecaca" }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: "#b91c1c", marginBottom: 6 }}>
                  Run Terminated (Fail-Closed)
                </div>
                <div style={{ fontSize: 12, color: "#991b1b" }}>{failure.reason}</div>
              </div>
            )}

            {/* Live Model Registry Status */}
            <ModelStatus />

            {/* Raw Model Inputs */}
            <ModelInputPanel scenario={scenario} setScenario={setScenario} />
          </div>
        </div>
      )}
    </div>
  );
}
