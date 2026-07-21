import { useState, useEffect, useCallback, useRef } from "react"
import Plot from "react-plotly.js"

const API = "http://localhost:8010/api/v1"
const DEV_API_KEY = "dev-key-so-a"
const POLL_MS = 4000

const ZONES = [
  { id: "zone-1", label: "Zone 1 - Coke Oven" },
  { id: "zone-2", label: "Zone 2 - Blast Furnace" },
  { id: "zone-3", label: "Zone 3 - Machine Shop" },
  { id: "zone-4", label: "Zone 4 - Shared Utilities" },
  { id: "zone-5", label: "Zone 5 - CCTV / PPE Checkpoints" },
  { id: "zone-6", label: "Zone 6 - Control Room" },
]

const DEMO_SCENARIO = {
  zone_risk: { "zone-1": 0.55 },
  hazard_severity: { "zone-1": 0.8 },
  active_paths: ["HE-042"],
  watch_zone: "zone-1",
  candidates: [
    { id: "suspend_permit", action: "Suspend hot-work permit", cost: 0.1, latency_s: 10, covers_paths: ["HE-042"] },
    { id: "close_barrier", action: "Close zone-1/zone-4 ventilation barrier", cost: 0.15, latency_s: 30, covers_paths: ["HE-042"] },
    { id: "evacuate", action: "Evacuate zone-1 workers", cost: 0.6, latency_s: 120, covers_paths: ["HE-042"] },
  ],
}

function riskColor(risk) {
  if (risk >= 0.75) return "bg-red-600"
  if (risk >= 0.4) return "bg-orange-500"
  if (risk >= 0.15) return "bg-yellow-400"
  return "bg-green-600"
}

async function safeJson(res) {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export default function App() {
  const [liveMode, setLiveMode] = useState(false)
  const [zoneRisk, setZoneRisk] = useState({})
  const [activePaths, setActivePaths] = useState([])
  const [recommendation, setRecommendation] = useState(null)
  const [trajectory, setTrajectory] = useState(null)
  const [auditTail, setAuditTail] = useState([])
  const [approvalStatus, setApprovalStatus] = useState(null)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  const pollLive = useCallback(async () => {
    try {
      const [paths, rec] = await Promise.all([
        fetch(`${API}/risk/paths`).then(safeJson),
        fetch(`${API}/risk/recommendation`).then(safeJson),
      ])
      setLiveMode(true)
      setError(null)
      setActivePaths(paths.active_paths ?? [])
      setRecommendation(rec.recommendation ?? null)

      const risk = {}
      for (const p of paths.active_paths ?? []) {
        for (const z of p.zones ?? []) {
          risk[z] = Math.max(risk[z] ?? 0, p.severity ?? 0)
        }
      }
      setZoneRisk(risk)
    } catch (err) {
      setLiveMode(false)
      setZoneRisk(DEMO_SCENARIO.zone_risk)
      setActivePaths(DEMO_SCENARIO.active_paths)
    }
  }, [])

  useEffect(() => {
    pollLive()
    pollRef.current = setInterval(pollLive, POLL_MS)
    return () => clearInterval(pollRef.current)
  }, [pollLive])

  async function runSimulation() {
    setError(null)
    try {
      const body = liveMode
        ? { use_live_graph: true, horizon_seconds: 300, dt_seconds: 10,
            close_barrier_edge: ["zone-1", "zone-4"], close_barrier_at_s: 30, close_barrier_magnitude: 0.05 }
        : { use_live_graph: false, ...DEMO_SCENARIO, horizon_seconds: 300, dt_seconds: 10,
            close_barrier_edge: ["zone-1", "zone-4"], close_barrier_at_s: 30, close_barrier_magnitude: 0.05 }

      const data = await fetch(`${API}/causal-cut/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(safeJson)
      setTrajectory(data)
    } catch (err) {
      setError(err.message)
    }
  }

  async function decide(decision) {
    setError(null)
    try {
      const res = await fetch(`${API}/risk/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": DEV_API_KEY },
        body: JSON.stringify({ recommendation_id: "current", decision, reason: "" }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail ?? `approval failed: ${res.status}`)
        return
      }
      setApprovalStatus(data)
      const tail = await fetch(`${API}/risk/audit?limit=10`).then(safeJson)
      setAuditTail(tail.records ?? [])
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 p-8">
      <div className="max-w-6xl mx-auto space-y-8">

        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">CAUSALCUT - Operator Console</h1>
            <p className="text-neutral-400 text-sm mt-1">Steelforge Industries | Minimum-Causal-Cut Safety Twin</p>
          </div>
          <span className={`text-xs px-3 py-1 rounded-full font-medium ${liveMode ? "bg-green-900 text-green-300" : "bg-yellow-900 text-yellow-300"}`}>
            {liveMode ? "LIVE - hypergraph engine connected" : "DEMO MODE - /risk/* not reachable"}
          </span>
        </header>

        <button onClick={runSimulation} className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 font-medium transition">
          Run What-If Simulation (close zone-1/zone-4 barrier)
        </button>

        {error && (
          <div className="rounded-lg border border-red-700 bg-red-950 text-red-300 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        <section>
          <h2 className="text-sm font-medium text-neutral-400 uppercase tracking-wide mb-3">Factory Zone Map</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {ZONES.map((zone) => {
              const risk = zoneRisk[zone.id] ?? 0
              return (
                <div key={zone.id} className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{zone.label}</span>
                    <span className={`w-3 h-3 rounded-full ${riskColor(risk)}`} />
                  </div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums">{risk.toFixed(2)}</div>
                  <div className="text-xs text-neutral-500">current risk [{liveMode ? "P" : "S"}]</div>
                </div>
              )
            })}
          </div>
        </section>

        {activePaths.length > 0 && (
          <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-5">
            <h2 className="text-sm font-medium text-neutral-400 uppercase tracking-wide mb-3">Active Accident Pathways</h2>
            <ul className="space-y-1 text-sm">
              {activePaths.map((p, i) => (
                <li key={p.hyperedge_id ?? i} className="text-neutral-300">
                  {p.hyperedge_id ?? p} {p.pathway ? `— ${p.pathway}` : ""}
                </li>
              ))}
            </ul>
          </section>
        )}

        {trajectory && (
          <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-5">
            <h2 className="text-sm font-medium text-neutral-400 uppercase tracking-wide mb-3">
              Zone-4 Risk - Baseline vs. Intervention
            </h2>
            <Plot
              data={[
                {
                  x: trajectory.timestamps_s,
                  y: trajectory.baseline["zone-4"],
                  type: "scatter", mode: "lines", name: "Do nothing [C]",
                  line: { color: "#ef4444", dash: "dot" },
                },
                ...(trajectory.treated ? [{
                  x: trajectory.timestamps_s,
                  y: trajectory.treated["zone-4"],
                  type: "scatter", mode: "lines", name: "Close barrier @30s [C]",
                  line: { color: "#22c55e" },
                }] : []),
              ]}
              layout={{
                paper_bgcolor: "transparent", plot_bgcolor: "transparent",
                font: { color: "#e5e5e5" }, margin: { t: 10, r: 10, l: 40, b: 40 },
                height: 320, xaxis: { title: "seconds" }, yaxis: { title: "risk", range: [0, 1] },
                legend: { orientation: "h", y: -0.2 },
              }}
              config={{ displayModeBar: false }}
              style={{ width: "100%" }}
            />
          </section>
        )}

        <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="text-sm font-medium text-neutral-400 uppercase tracking-wide mb-3">
            Minimum-Causal-Cut Recommendation
          </h2>

          <ul className="space-y-2 mb-4">
            {(liveMode ? (recommendation?.interventions ?? []) : DEMO_SCENARIO.candidates).map((c) => (
              <li key={c.intervention_id ?? c.id} className="flex items-center justify-between rounded-lg bg-neutral-800 px-3 py-2 text-sm">
                <span>{c.action}</span>
                <span className="text-neutral-400 text-xs">
                  {c.cost_category ?? c.cost} | {c.execution_time_min ? `${c.execution_time_min}min` : `${c.latency_s}s`}
                </span>
              </li>
            ))}
          </ul>

          <p className="text-xs text-neutral-500 mb-3">
            This is a recommendation only. No action executes without explicit human approval.
          </p>

          {approvalStatus === null ? (
            <div className="flex gap-2">
              <button onClick={() => decide("APPROVE")} className="px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-sm font-medium">
                [H] Approve
              </button>
              <button onClick={() => decide("REJECT")} className="px-4 py-2 rounded-lg bg-neutral-700 hover:bg-neutral-600 text-sm font-medium">
                [H] Reject
              </button>
            </div>
          ) : (
            <div className={`text-sm font-medium ${approvalStatus.decision === "APPROVE" ? "text-green-400" : "text-neutral-400"}`}>
              {approvalStatus.decision} by {approvalStatus.approver} — audit seq #{approvalStatus.audit_seq}
              {approvalStatus.dispatched ? " — dispatched" : ""}
            </div>
          )}
        </section>

        {auditTail.length > 0 && (
          <section className="rounded-xl border border-neutral-800 bg-neutral-900 p-5">
            <h2 className="text-sm font-medium text-neutral-400 uppercase tracking-wide mb-3">Audit Trail (last 10)</h2>
            <ul className="space-y-1 text-xs font-mono text-neutral-400">
              {auditTail.map((r) => (
                <li key={r.seq}>
                  #{r.seq} {r.timestamp} — {r.decision} by {r.approver_id} ({r.approver_role})
                </li>
              ))}
            </ul>
          </section>
        )}

      </div>
    </div>
  )
}
