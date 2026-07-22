// Shows exactly which trained models were called, which actually ran, the
// artifact loaded, latency, confidence and any degraded reason. This is how the
// operator can tell real inference from degraded/unavailable at a glance.
export default function ModelProvenance({ models, executionMode, correlationId, scenarioId }) {
  if (!models) return null;
  const inv = models.invocations || [];
  const modeClass =
    executionMode === "real" ? "s-normal" : executionMode === "degraded" ? "s-warning" : "s-mitigated";

  return (
    <div className="panel">
      <div className="panel-title">
        Model Inference Provenance
        <span style={{ marginLeft: "auto" }} className={`mono ${modeClass}`}>
          execution mode: {executionMode}
        </span>
      </div>

      <div className="dim mono" style={{ fontSize: 11, marginBottom: 10 }}>
        scenario <b>{scenarioId}</b> · correlation <b>{correlationId}</b> ·
        mocks used: <b>{String(models.mocks_used)}</b>
      </div>

      {inv.length === 0 ? (
        <div className="faint mono" style={{ fontSize: 12 }}>
          No model inputs were supplied in this scenario (no raw gas, machine,
          hydraulic, vision or tracking inputs), so no inference services were
          invoked.
        </div>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>called</th><th>model</th><th>version</th><th>mode</th>
              <th>conf</th><th>latency</th><th>artifact</th>
            </tr>
          </thead>
          <tbody>
            {inv.map((m, i) => (
              <tr key={i}>
                <td className="mono">{m.called}</td>
                <td>{m.model_name}</td>
                <td className="mono" style={{ fontSize: 10 }}>{m.model_version}</td>
                <td className={m.ran ? "s-normal" : "s-critical"}>
                  {m.ran ? "real" : m.inference_mode}
                </td>
                <td className="mono">{m.confidence != null ? m.confidence.toFixed(3) : "—"}</td>
                <td className="mono">{m.latency_ms != null ? `${m.latency_ms} ms` : "—"}</td>
                <td className="faint mono" style={{ fontSize: 10 }}>
                  {m.artifact_path ? String(m.artifact_path).split("/").slice(-1)[0] : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {inv.filter((m) => !m.ran).length > 0 && (
        <div style={{ marginTop: 12 }}>
          {inv.filter((m) => !m.ran).map((m, i) => (
            <div className="warn" key={i}>
              ⚠ <b>{m.model_name}</b> did not run ({m.inference_mode}): {m.degraded_reason}
              <div className="faint" style={{ marginTop: 3 }}>
                No substitute prediction was generated for this model.
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
