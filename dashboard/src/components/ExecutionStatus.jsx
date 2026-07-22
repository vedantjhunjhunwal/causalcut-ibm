// Live per-stage pipeline progress.
//
// This mirrors the backend's canonical stage vocabulary (app/engine/
// scenario_pipeline.py :: STAGES) one-for-one. A stage lights up only when the
// backend has actually reported it over /ws/scenarios/{run_id} — or, if the
// socket is unavailable, when it appears in the recorded stage history
// returned by GET /scenario/runs/{run_id}. Nothing here advances on a timer.

const STAGES = [
  ["validating", "Scenario validation"],
  ["model_inference", "Model inference"],
  ["persisting_events", "Event persistence"],
  ["queue_processing", "Queue processing"],
  ["state_projection", "SQLite state projection"],
  ["hypergraph_update", "Hypergraph update"],
  ["rule_evaluation", "Compound-rule activation"],
  ["path_extraction", "Causal-path extraction"],
  ["risk_propagation", "Risk propagation"],
  ["simulation", "Counterfactual simulation"],
  ["optimization", "Minimum-causal-cut optimisation"],
  ["regulatory_verification", "Regulatory verification"],
];

// Backend status -> row appearance.
const CLASS_FOR = {
  ok: "done",
  running: "active",
  partial: "warn",
  timeout: "warn",
  error: "fail",
};

const MARK_FOR = { done: "✓", active: "•", warn: "!", fail: "×", pending: null };

/** One-line summary of what the backend reported for this stage. */
function detail(key, msg) {
  if (!msg) return null;
  const bits = [];
  switch (key) {
    case "model_inference": {
      const ran = msg.models_ran?.length ?? 0;
      const failed = msg.models_failed?.length ?? 0;
      if (msg.status !== "running") {
        bits.push(`${ran} model${ran === 1 ? "" : "s"} ran`);
        if (failed) bits.push(`${failed} unavailable`);
        if (msg.events != null) bits.push(`${msg.events} event(s)`);
      }
      break;
    }
    case "persisting_events":
      if (msg.persisted != null) bits.push(`${msg.persisted} persisted`);
      if (msg.rejected) bits.push(`${msg.rejected} rejected`);
      else if (msg.total != null && msg.persisted == null) bits.push(`${msg.total} queued`);
      break;
    case "queue_processing":
      if (msg.processed != null) bits.push(`${msg.processed}/${msg.expected} processed`);
      else if (msg.expected != null) bits.push(`${msg.expected} expected`);
      if (msg.failed) bits.push(`${msg.failed} failed`);
      break;
    case "state_projection":
      if (msg.projected != null) bits.push(`${msg.projected} projected`);
      break;
    case "hypergraph_update":
      if (msg.applied != null) bits.push(`${msg.applied} applied`);
      if (msg.skipped) bits.push(`${msg.skipped} not graph-relevant`);
      break;
    default:
      break;
  }
  if (msg.error) bits.push(String(msg.error).slice(0, 80));
  if (!bits.length && msg.elapsed_ms != null) bits.push(`${Math.round(msg.elapsed_ms)} ms`);
  return bits.join(" · ") || null;
}

export default function ExecutionStatus({ phase, stages = {}, latest, failedStage }) {
  // phase: 'idle' | 'running' | 'done' | 'error'
  const finished = Boolean(stages.completed) || phase === "done";

  return (
    <div className="panel">
      <div className="panel-title">
        Execution Status
        {phase === "running" && (
          <span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: "var(--ink-faint)" }}>
            {latest?.label ?? "waiting for backend…"}
          </span>
        )}
      </div>

      {phase === "idle" && (
        <div className="faint mono" style={{ fontSize: 11, marginBottom: 8 }}>
          Not started. Stages populate from the backend as the pipeline runs.
        </div>
      )}

      <div className="stages">
        {STAGES.map(([key, label], i) => {
          const msg = stages[key];
          let cls = "pending";
          if (key === failedStage && phase === "error") cls = "fail";
          else if (msg) cls = CLASS_FOR[msg.status] ?? "done";
          // The pipeline reports analysis stages once, on success; a terminal
          // "completed" therefore implies every earlier stage passed.
          else if (finished) cls = "done";

          const mark = MARK_FOR[cls] ?? i + 1;
          const info = detail(key, msg);

          return (
            <div key={key} className={`stage ${cls}`}>
              <span className="ic">{mark ?? i + 1}</span>
              <span className="lbl">{label}</span>
              {info && <span className="stage-meta mono">{info}</span>}
            </div>
          );
        })}
      </div>

      {stages.completed && (
        <div className="audit-ok" style={{ marginTop: 10 }}>
          ✓ Pipeline completed
          {stages.completed.elapsed_ms != null &&
            ` in ${Math.round(stages.completed.elapsed_ms)} ms`}
          {stages.completed.rules != null &&
            ` · ${stages.completed.rules} compound rule(s) activated`}
        </div>
      )}
      {stages.failed && (
        <div className="err-msg" style={{ marginTop: 10 }}>
          {stages.failed.error || "Pipeline failed."}
        </div>
      )}
    </div>
  );
}
