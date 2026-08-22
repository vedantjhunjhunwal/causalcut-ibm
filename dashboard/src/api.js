// API client for CAUSALCUT Safety Intelligence backend.

export const API = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api/v1";
export const DEV_API_KEY = import.meta.env.VITE_OPERATOR_KEY ?? "dev-key-so-a";

async function json(res) {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body?.detail || body?.error || `${res.status} ${res.statusText}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

async function envelope(res) {
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, body };
}

export const api = {
  // Scenario & Simulation
  template: () => fetch(`${API}/scenario/template`).then(json),
  samples: () => fetch(`${API}/scenario/samples`).then(json),
  sample: (name) => fetch(`${API}/scenario/sample/${name}`).then(json),
  validate: (scenario) =>
    fetch(`${API}/scenario/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scenario),
    }).then(json),
  start: (scenario) =>
    fetch(`${API}/scenario/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scenario),
    }).then(envelope),
  runStatus: (runId) => fetch(`${API}/scenario/runs/${runId}`).then(json),
  getRun: (runId) => fetch(`${API}/scenario/${runId}`).then(json),
  getGraph: (runId) => fetch(`${API}/scenario/${runId}/graph`).then(json),
  decide: (runId, decision, reason) =>
    fetch(`${API}/scenario/${runId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": DEV_API_KEY },
      body: JSON.stringify({ decision, reason }),
    }).then(envelope),

  // Plant State
  zoneState: (zoneId) => fetch(`${API}/state/zones/${zoneId}`).then(json).catch(() => null),
  permits: () => fetch(`${API}/state/permits`).then(json).catch(() => ({ count: 0, permits: [] })),
  workers: (nonCompliantOnly = false) =>
    fetch(`${API}/state/workers?non_compliant_only=${nonCompliantOnly}`)
      .then(json)
      .catch(() => ({ count: 0, workers: [] })),
  sensorHistory: (sensorId, limit = 100) =>
    fetch(`${API}/state/sensors/${sensorId}/history?limit=${limit}`)
      .then(json)
      .catch(() => ({ count: 0, readings: [] })),

  // Risk & Interventions & Governance
  riskPaths: () => fetch(`${API}/risk/paths`).then(json).catch(() => null),
  riskRecommendation: () => fetch(`${API}/risk/recommendation`).then(json).catch(() => null),
  approveRecommendation: (decision, reason, recommendationId = "current") =>
    fetch(`${API}/risk/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": DEV_API_KEY },
      body: JSON.stringify({ decision, reason, recommendation_id: recommendationId }),
    }).then(envelope),
  audit: (limit = 50) => fetch(`${API}/risk/audit?limit=${limit}`).then(json),
  handoverValidate: (handover) =>
    fetch(`${API}/handover/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(handover),
    }).then(json),

  // Live Events Stream
  events: (limit = 50, zoneId = null, eventType = null) => {
    let url = `${API}/events?limit=${limit}`;
    if (zoneId) url += `&zone_id=${zoneId}`;
    if (eventType) url += `&event_type=${eventType}`;
    return fetch(url).then(json).catch(() => ({ count: 0, events: [] }));
  },

  // Health & System
  health: () => fetch(`${API}/health`).then(json).catch(() => null),
  ready: () => fetch(`${API}/ready`).then(json).catch(() => null),
  stats: () => fetch(`${API}/stats`).then(json).catch(() => null),
  modelStatus: () => fetch(`${API}/models/status`).then(json).catch(() => null),
  modelReadiness: () => fetch(`${API}/models/readiness`).then(json).catch(() => null),

  // --- Agent API functions ---
  agentStatus: async () => fetch(`${API}/agents/status`).then(json),
  agentSituation: async () => fetch(`${API}/agents/situation`).then(json),
  agentAlerts: async (limit = 20) => fetch(`${API}/agents/alerts?limit=${limit}`).then(json),
  agentProposals: async () => fetch(`${API}/agents/proposals`).then(json),
  agentProposalDetail: async (id) => fetch(`${API}/agents/proposals/${id}`).then(json),
  decideProposal: async (id, decision, notes = '') =>
    fetch(`${API}/agents/proposals/${id}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, notes })
    }).then(json),
  agentChat: async (sessionId, message) =>
    fetch(`${API}/agents/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message })
    }).then(json),
  agentChatHistory: async (sessionId, limit = 50) =>
    fetch(`${API}/agents/chat/history?session_id=${sessionId}&limit=${limit}`).then(json),
  agentCompliance: async () => fetch(`${API}/agents/compliance`).then(json),
  agentConfig: async (config) =>
    fetch(`${API}/agents/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    }).then(json),
};

// ---------------------------------------------------------------------------
// Progress socket for asynchronous pipeline execution
// ---------------------------------------------------------------------------
export const WS_BASE =
  import.meta.env.VITE_WS_BASE ?? API.replace(/^http/, "ws").replace(/\/api\/v1$/, "");

export const TERMINAL_STAGES = new Set(["completed", "failed"]);

const POLL_INTERVAL_MS = 1500;
const SETTLE_RETRIES = 10;
const SETTLE_DELAY_MS = 300;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class ProgressSocket {
  constructor({ onStage, onState, onSettled, onError } = {}) {
    this.onStage = onStage;
    this.onState = onState;
    this.onSettled = onSettled;
    this.onError = onError;

    this.ws = null;
    this.runId = null;
    this.attempt = 0;
    this.maxAttempts = 6;
    this.closedByUs = false;
    this.settled = false;
    this.seen = new Set();
    this.pollTimer = null;
  }

  subscribe(runId) {
    this.runId = runId;
    this.settled = false;
    this.closedByUs = false;
    this.attempt = 0;
    this.seen.clear();
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* noop */
      }
    }
    this._open();
  }

  _key(msg) {
    return `${msg.stage}|${msg.status ?? ""}|${msg.index ?? ""}`;
  }

  _emit(msg) {
    if (!msg || !msg.stage) return;
    if (msg.stage === "subscribed") return;
    if (this.runId && msg.run_id && msg.run_id !== this.runId) return;
    const key = this._key(msg);
    if (this.seen.has(key)) return;
    this.seen.add(key);
    this.onStage?.(msg);
    if (TERMINAL_STAGES.has(msg.stage)) this._settle();
  }

  _open() {
    if (this.settled || this.closedByUs) return;
    this.onState?.(this.attempt === 0 ? "connecting" : "reconnecting");
    let ws;
    try {
      ws = new WebSocket(`${WS_BASE}/api/v1/ws/scenarios/${this.runId}`);
    } catch {
      return this._retry();
    }
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this._stopPolling();
      this.onState?.("open");
    };

    ws.onmessage = (e) => {
      let msg;
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }
      this._emit(msg);
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        /* noop */
      }
    };

    ws.onclose = () => {
      if (this.settled || this.closedByUs) {
        this.onState?.("closed");
        return;
      }
      this._retry();
    };
  }

  _retry() {
    if (this.settled || this.closedByUs) return;
    this._startPolling();
    if (this.attempt >= this.maxAttempts) {
      this.onState?.("polling");
      return;
    }
    const delay = Math.min(1000 * 2 ** this.attempt, 15000);
    this.attempt += 1;
    setTimeout(() => {
      if (!this.closedByUs && !this.settled) this._open();
    }, delay);
  }

  _startPolling() {
    if (this.pollTimer || !this.runId || this.settled) return;
    const tick = async () => {
      if (this.settled || this.closedByUs) return;
      try {
        const data = await api.runStatus(this.runId);
        (data.progress || []).forEach((m) => this._emit({ ...m, polled: true }));
        if (data.status && data.status !== "running") this._settle(data);
      } catch {
        /* keep polling */
      }
    };
    this.pollTimer = setInterval(tick, POLL_INTERVAL_MS);
    tick();
  }

  _stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  async _settle(known) {
    if (this.settled) return;
    this.settled = true;
    this._stopPolling();

    let data = known;
    for (let i = 0; i < SETTLE_RETRIES; i += 1) {
      if (data && data.status && data.status !== "running" && data.result) break;
      try {
        data = await api.runStatus(this.runId);
      } catch (err) {
        if (i === SETTLE_RETRIES - 1) {
          this.close();
          this.onError?.(err);
          return;
        }
      }      if (data && data.status && data.status !== "running" && data.result) break;
      await sleep(SETTLE_DELAY_MS);
    }

    this.close();

    if (!data || !data.result) {
      this.onError?.(new Error("Run finished but the backend returned no result document."));
      return;
    }
    this.onSettled?.({
      status: data.status ?? data.result?.status ?? "completed",
      result: data.result,
      progress: data.progress || [],
    });
  }

  close() {
    this.closedByUs = true;
    this._stopPolling();
    try {
      this.ws?.close();
    } catch {
      /* noop */
    }
    this.ws = null;
  }
}

export class AgentEventSocket {
  constructor(onEvent) {
    const wsBase = import.meta.env.VITE_WS_BASE || 'ws://localhost:8000';
    this.ws = new WebSocket(`${wsBase}/api/v1/ws/agents/events`);
    this.ws.onmessage = (e) => onEvent(JSON.parse(e.data));
    this.ws.onerror = () => console.warn('Agent event WS error');
  }
  close() { this.ws?.close(); }
}

export class AgentChatSocket {
  constructor(sessionId, onMessage, onToolUse) {
    const wsBase = import.meta.env.VITE_WS_BASE || 'ws://localhost:8000';
    this.ws = new WebSocket(`${wsBase}/api/v1/ws/agents/chat/${sessionId}`);
    this.ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === 'tool_use') onToolUse?.(data);
      else onMessage?.(data);
    };
  }
  send(message) { this.ws?.send(JSON.stringify({ message })); }
  close() { this.ws?.close(); }
}
