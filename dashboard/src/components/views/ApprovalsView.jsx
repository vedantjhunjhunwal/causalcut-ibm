import React, { useState, useEffect } from "react";
import { ClipboardCheck, Check, X, RefreshCw } from "lucide-react";
import { api } from "../../api";

export default function ApprovalsView({ result, runId, onNavigate }) {
  const [decisions, setDecisions] = useState({});
  const [alternativeInputs, setAlternativeInputs] = useState({});
  const [loading, setLoading] = useState(false);
  const [showAlternativeFor, setShowAlternativeFor] = useState(null);
  const [submittingAlt, setSubmittingAlt] = useState(false);
  // Tracks interventions that were already decided at the run level
  const [alreadyDecidedFor, setAlreadyDecidedFor] = useState({});

  // Hydrate decisions from audit log AND from any existing run-level decision
  useEffect(() => {
    const hydrate = async () => {
      // 1. Try to get the existing run decision (fast path)
      if (runId) {
        try {
          const runResp = await fetch(
            `${api.baseUrl ?? "http://localhost:8000/api/v1"}/scenario/runs/${runId}`
          );
          if (runResp.ok) {
            const runBody = await runResp.json();
            if (runBody?.decision) {
              // The whole run was already decided — pre-fill every intervention
              const runDecisionValue = runBody.decision?.decision ?? runBody.decision;
              const runDecisionRecord = typeof runBody.decision === "object" ? runBody.decision : {};
              setAlreadyDecidedFor((prev) => {
                const next = { ...prev };
                (result?.recommendation?.interventions ?? []).forEach((iv) => {
                  const id = iv.intervention_id;
                  if (id) next[id] = runDecisionRecord;
                });
                return next;
              });
              setDecisions((prev) => {
                const next = { ...prev };
                (result?.recommendation?.interventions ?? []).forEach((iv) => {
                  const id = iv.intervention_id;
                  if (id && !next[id]) next[id] = runDecisionValue;
                });
                return next;
              });
            }
          }
        } catch (e) {
          console.warn("Run decision hydration failed:", e);
        }
      }

      // 2. Also hydrate from audit log (per-intervention decisions)
      try {
        const resp = await fetch(`${api.baseUrl ?? "http://localhost:8000/api/v1"}/risk/audit?limit=100`);
        const body = await resp.json();
        if (resp.ok && Array.isArray(body)) {
          const past = {};
          body.forEach((log) => {
            if (Array.isArray(log.interventions)) {
              log.interventions.forEach((invId) => {
                past[invId] = log.decision;
              });
            }
          });
          setDecisions((prev) => ({ ...past, ...prev })); // run-level wins over audit
        }
      } catch (e) {
        console.warn("Audit hydration failed:", e);
      }
    };
    hydrate();
  }, [runId]);


  const pendingApprovals = (result?.recommendation?.interventions ?? []).map((iv, idx) => ({
    id: iv.intervention_id ?? `INT-${Date.now()}-${idx}`,
    title: `${iv.action}`,
    zone: iv.target_zone ?? "Plant",
    requestedBy: "Risk Inference Engine",
    expectedRiskReduction: iv.risk_reduction != null
      ? `-${Math.round(iv.risk_reduction * 100)}%`
      : "—",
    costCategory: iv.cost_category ?? "unknown",
    disruption: iv.disruption ?? "medium",
    execTime: iv.execution_time_min != null ? `${iv.execution_time_min} min` : "—",
    urgency: idx === 0 ? "HIGH" : idx === 1 ? "MEDIUM" : "LOW",
    details: iv.breaks_factors?.length
      ? `Stopping causal chain: ${iv.breaks_factors.join(" → ")}.`
      : "Automated intervention request from causal cut optimization.",
    breaksFactors: iv.breaks_factors ?? [],
  }));

  const handleDecision = async (id, decision) => {
    if (!runId) {
      alert("No active run to record decision for. Please run a simulation first.");
      return;
    }
    setLoading(true);
    try {
      const resp = await api.decide(
        runId,
        decision,
        `${decision} by Shift Officer via Approvals Queue (intervention: ${id})`
      );
      if (resp.ok) {
        setDecisions((prev) => ({ ...prev, [id]: decision }));
        if (decision === "REJECT") {
          setShowAlternativeFor(id);
        }
      } else if (resp.status === 409) {
        // Run was already decided (e.g. approved from the Results view).
        // Extract the existing decision and reflect it in the UI — no error shown.
        const existingDecision =
          typeof resp.body?.detail === "object"
            ? resp.body.detail?.decision
            : resp.body?.error === "already_decided"
            ? "APPROVE"
            : null;
        if (existingDecision) {
          setDecisions((prev) => ({ ...prev, [id]: existingDecision }));
          setAlreadyDecidedFor((prev) => ({ ...prev, [id]: resp.body?.detail ?? {} }));
        } else {
          setDecisions((prev) => ({ ...prev, [id]: "APPROVE" }));
          setAlreadyDecidedFor((prev) => ({ ...prev, [id]: {} }));
        }
      } else {
        const errMsg =
          typeof resp.body?.detail === "string"
            ? resp.body.detail
            : typeof resp.body?.detail === "object"
            ? JSON.stringify(resp.body.detail)
            : resp.body?.error ?? `HTTP ${resp.status}`;
        alert(`Failed to record decision: ${errMsg}`);
      }
    } catch (e) {
      alert(`Network error: ${e.message ?? String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAlternativeInput = (id, field, value) => {
    setAlternativeInputs((prev) => ({
      ...prev,
      [id]: { ...(prev[id] ?? {}), [field]: value },
    }));
  };

  const submitAlternative = async (appr) => {
    if (!runId) return;
    const altData = alternativeInputs[appr.id] ?? {};
    if (!altData.alternative_action?.trim()) {
      alert("Please describe the alternative action before submitting.");
      return;
    }
    setSubmittingAlt(true);
    try {
      const payload = {
        alternative_action: altData.alternative_action,
        breaks_factors: altData.selected_factors ?? appr.breaksFactors,
        operator_confidence: altData.confidence ?? 3,
        reason: altData.reason ?? "",
        original_intervention_id: appr.id,
      };
      const resp = await api.submitAlternative(runId, payload);
      if (resp.ok) {
        setShowAlternativeFor(null);
        alert("Alternative recorded — this will be used as a learning signal for the model.");
      } else {
        alert(`Failed to submit alternative: ${resp.body?.detail ?? "Unknown"}`);
      }
    } catch (e) {
      alert(`Submit error: ${e.message}`);
    } finally {
      setSubmittingAlt(false);
    }
  };

  return (
    <div className="page-canvas">
      <div className="page-header">
        <div>
          <div className="breadcrumbs">GOVERNANCE / HUMAN-IN-THE-LOOP</div>
          <h1 className="page-title">Pending Approvals Queue</h1>
          <div className="page-subtitle">
            Authority-gated shift officer approvals before safety interventions are dispatched.
            {!runId && (
              <span style={{ color: "#d97706", fontWeight: 600 }}>
                {" "}Run a simulation to generate intervention recommendations.
              </span>
            )}
          </div>
        </div>
        {pendingApprovals.length > 0 && (
          <div style={{ fontSize: 12, color: "#64748b" }}>
            {pendingApprovals.filter((a) => !decisions[a.id]).length} awaiting decision
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {pendingApprovals.length === 0 ? (
          <div className="panel-box" style={{ padding: 40, textAlign: "center", color: "#64748b" }}>
            <ClipboardCheck size={32} style={{ marginBottom: 12, opacity: 0.4 }} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {result ? "No interventions pending" : "No active simulation run"}
            </div>
            <div style={{ fontSize: 12 }}>
              {result
                ? "The system found no pathways requiring intervention approval."
                : "Run a scenario from the Simulation Studio to generate recommendations."}
            </div>
            {!result && (
              <button
                className="action-btn primary"
                style={{ marginTop: 16 }}
                onClick={() => onNavigate?.("simulation")}
              >
                Go to Simulation →
              </button>
            )}
          </div>
        ) : (
          pendingApprovals.map((appr) => {
            const status = decisions[appr.id];
            const isAwaiting = !status;
            const showAlt = showAlternativeFor === appr.id;
            const altState = alternativeInputs[appr.id] ?? {};

            return (
              <div key={appr.id} className="panel-box" style={{ padding: 20 }}>
                {/* Header row */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                      {appr.id}
                    </span>
                    <span className={`badge-pill ${appr.urgency.toLowerCase()}`}>
                      ● {appr.urgency}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#64748b" }}>
                    <span>Cost: <b>{appr.costCategory}</b></span>
                    <span>Disruption: <b>{appr.disruption}</b></span>
                    <span>Exec: <b>{appr.execTime}</b></span>
                  </div>
                </div>

                <h3 style={{ margin: "0 0 4px 0", fontSize: 16, fontWeight: 700 }}>
                  {appr.title}
                </h3>
                <div style={{ fontSize: 12, color: "#64748b", marginBottom: 6 }}>
                  Target zone: <b>{appr.zone}</b> · Requested by: {appr.requestedBy}
                </div>
                <p style={{ margin: "0 0 14px 0", fontSize: 12.5, color: "#475569", lineHeight: 1.5 }}>
                  {appr.details}
                </p>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid #f1f5f9", paddingTop: 14 }}>
                  <div style={{ fontSize: 12, color: "#047857", fontWeight: 700 }}>
                    Expected Risk Reduction: {appr.expectedRiskReduction}
                  </div>

                  {status ? (
                  <span style={{
                    padding: "6px 12px", borderRadius: 4, fontSize: 12, fontWeight: 700,
                    backgroundColor: status === "APPROVE" ? "#ecfdf5" : "#fef2f2",
                    color: status === "APPROVE" ? "#047857" : "#b91c1c",
                  }}>
                    ✓ {status} — recorded in tamper-evident audit log
                    {alreadyDecidedFor[appr.id] && (
                      <span style={{ fontWeight: 400, fontSize: 11, display: "block", marginTop: 4, color: "#64748b" }}>
                        Recorded at run level
                        {alreadyDecidedFor[appr.id]?.approver
                          ? ` by ${alreadyDecidedFor[appr.id].approver}`
                          : ""}
                        {alreadyDecidedFor[appr.id]?.timestamp
                          ? ` · ${new Date(alreadyDecidedFor[appr.id].timestamp).toLocaleTimeString()}`
                          : ""}
                      </span>
                    )}
                  </span>
                  ) : (
                    <div style={{ display: "flex", gap: 10 }}>
                      <button
                        className="action-btn"
                        style={{ color: "#b91c1c" }}
                        onClick={() => handleDecision(appr.id, "REJECT")}
                        disabled={loading}
                      >
                        <X size={14} />
                        <span>Reject</span>
                      </button>
                      <button
                        className="action-btn primary"
                        onClick={() => handleDecision(appr.id, "APPROVE")}
                        disabled={loading}
                      >
                        <Check size={14} />
                        <span>Approve & Dispatch</span>
                      </button>
                    </div>
                  )}
                </div>

                {/* ── Alternative Input Panel — shown after REJECT ─────────────── */}
                {status === "REJECT" && showAlt && (
                  <div style={{
                    marginTop: 16, padding: 16,
                    backgroundColor: "#fffbeb", border: "1px solid #fde68a",
                    borderRadius: 6,
                  }}>
                    <div style={{ fontWeight: 700, fontSize: 13, color: "#92400e", marginBottom: 10 }}>
                      📝 What would you have done instead?
                    </div>
                    <div style={{ fontSize: 12, color: "#78350f", marginBottom: 12, lineHeight: 1.5 }}>
                      Your alternative will be logged as an operator learning signal. This helps the system improve recommendations over time based on your real-world expertise.
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <div>
                        <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", display: "block", marginBottom: 4 }}>
                          ALTERNATIVE ACTION *
                        </label>
                        <input
                          type="text"
                          placeholder="e.g. Evacuate zone and call maintenance team…"
                          style={{
                            width: "100%", padding: "8px 10px", fontSize: 12.5,
                            border: "1px solid #d97706", borderRadius: 4, boxSizing: "border-box",
                          }}
                          value={altState.alternative_action ?? ""}
                          onChange={(e) => handleAlternativeInput(appr.id, "alternative_action", e.target.value)}
                        />
                      </div>

                      {appr.breaksFactors.length > 0 && (
                        <div>
                          <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", display: "block", marginBottom: 4 }}>
                            WHICH CAUSAL FACTORS DOES YOUR ACTION ADDRESS?
                          </label>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                            {appr.breaksFactors.map((factor) => {
                              const selected = (altState.selected_factors ?? []).includes(factor);
                              return (
                                <button
                                  key={factor}
                                  onClick={() => {
                                    const cur = altState.selected_factors ?? [];
                                    handleAlternativeInput(
                                      appr.id,
                                      "selected_factors",
                                      selected ? cur.filter((f) => f !== factor) : [...cur, factor]
                                    );
                                  }}
                                  style={{
                                    padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 600, cursor: "pointer",
                                    border: `1.5px solid ${selected ? "#d97706" : "#e2e8f0"}`,
                                    backgroundColor: selected ? "#fef3c7" : "#f8fafc",
                                    color: selected ? "#92400e" : "#64748b",
                                  }}
                                >
                                  {factor.replace(/_/g, " ")}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      <div>
                        <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", display: "block", marginBottom: 4 }}>
                          OPERATOR CONFIDENCE (1 = uncertain, 5 = certain)
                        </label>
                        <div style={{ display: "flex", gap: 6 }}>
                          {[1, 2, 3, 4, 5].map((n) => (
                            <button
                              key={n}
                              onClick={() => handleAlternativeInput(appr.id, "confidence", n)}
                              style={{
                                width: 34, height: 34, borderRadius: "50%", border: "1.5px solid",
                                cursor: "pointer", fontSize: 13, fontWeight: 700,
                                borderColor: altState.confidence === n ? "#d97706" : "#e2e8f0",
                                backgroundColor: altState.confidence === n ? "#fef3c7" : "#f8fafc",
                                color: altState.confidence === n ? "#92400e" : "#64748b",
                              }}
                            >
                              {n}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div>
                        <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", display: "block", marginBottom: 4 }}>
                          REASON / CONTEXT (optional)
                        </label>
                        <textarea
                          rows={2}
                          placeholder="e.g. SOP requires manual evacuation for ammonia readings above 250 ppm…"
                          style={{
                            width: "100%", padding: "8px 10px", fontSize: 12,
                            border: "1px solid #d97706", borderRadius: 4, boxSizing: "border-box",
                            resize: "vertical",
                          }}
                          value={altState.reason ?? ""}
                          onChange={(e) => handleAlternativeInput(appr.id, "reason", e.target.value)}
                        />
                      </div>

                      <div style={{ display: "flex", gap: 10 }}>
                        <button
                          className="action-btn primary"
                          style={{ backgroundColor: "#d97706", borderColor: "#d97706" }}
                          onClick={() => submitAlternative(appr)}
                          disabled={submittingAlt}
                        >
                          {submittingAlt ? <RefreshCw size={13} className="animate-spin" /> : null}
                          <span>{submittingAlt ? "Submitting…" : "Submit Learning Signal"}</span>
                        </button>
                        <button
                          className="action-btn"
                          onClick={() => setShowAlternativeFor(null)}
                        >
                          Skip
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
