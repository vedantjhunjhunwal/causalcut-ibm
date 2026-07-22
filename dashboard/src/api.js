// Thin API client for the CAUSALCUT backend. All scenario-driven — nothing
// here auto-runs; the caller decides when to POST /scenario/start.

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
  template: () => fetch(`${API}/scenario/template`).then(json),
  samples: () => fetch(`${API}/scenario/samples`).then(json),
  sample: (name) => fetch(`${API}/scenario/sample/${name}`).then(json),
  validate: (scenario) =>
    fetch(`${API}/scenario/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scenario),
    }).then(json),

  // Asynchronous execution is the ONLY execution path. 202 Accepted returns
  // run_id / scenario_id / correlation_id before the pipeline has done any
  // work, so the client can subscribe to progress from the very first stage
  // instead of blocking on a single long request.
  start: (scenario) =>
    fetch(`${API}/scenario/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scenario),
    }).then(envelope),

  // Authoritative status + result for a background run. Also carries the real
  // stage history, which is what the polling fallback renders.
  runStatus: (runId) => fetch(`${API}/scenario/runs/${runId}`).then(json),

  getRun: (runId) => fetch(`${API}/scenario/${runId}`).then(json),
  getGraph: (runId) => fetch(`${API}/scenario/${runId}/graph`).then(json),
  decide: (runId, decision, reason) =>
    fetch(`${API}/scenario/${runId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": DEV_API_KEY },
      body: JSON.stringify({ decision, reason }),
    }).then(envelope),
  audit: () => fetch(`${API}/risk/audit`).then(json),
  health: () => fetch(`${API}/health`).then(json).catch(() => null),
  modelStatus: () => fetch(`${API}/models/status`).then(json),
  modelReadiness: () => fetch(`${API}/models/readiness`).then(json),
};

// ---------------------------------------------------------------------------
// Progress socket.
//
// Every stage this emits originates from the backend pipeline — there are no
// client-side timers advancing a fake progress bar. If the socket cannot be
// held open we fall back to polling GET /scenario/runs/{run_id}, which returns
// the same recorded stage stream, so degraded transport costs granularity but
// never truthfulness.
//
//  * run-scoped subscription (/ws/scenarios/{run_id})
//  * automatic reconnection with capped exponential backoff
//  * gap-free: the server replays stages emitted before/while we connected
//  * duplicate suppression across replay, live feed and polling
//  * stays open until the run reports completion or failure
// ---------------------------------------------------------------------------
export const WS_BASE =
  import.meta.env.VITE_WS_BASE ?? API.replace(/^http/, "ws").replace(/\/api\/v1$/, "");

export const TERMINAL_STAGES = new Set(["completed", "failed"]);

const POLL_INTERVAL_MS = 1500;
const SETTLE_RETRIES = 10;
const SETTLE_DELAY_MS = 300;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class ProgressSocket {
  /**
   * @param {object}   handlers
   * @param {function} handlers.onStage    - one real backend stage message
   * @param {function} handlers.onState    - 'connecting'|'open'|'reconnecting'|'polling'|'closed'
   * @param {function} handlers.onSettled  - ({status, result}) once, when the run ends
   * @param {function} handlers.onError    - transport/fetch error we could not recover from
   */
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

  /** Subscribe to ONE run. The socket URL is run-scoped, so the server never
   *  sends another scenario's progress to this client. */
  subscribe(runId) {
    this.runId = runId;
    this.settled = false;
    this.closedByUs = false;
    this.attempt = 0;
    this.seen.clear();
    if (this.ws) { try { this.ws.close(); } catch { /* noop */ } }
    this._open();
  }

  // -- stage plumbing -------------------------------------------------------

  /** Stable across WebSocket replay, live feed and polled history: the same
   *  pipeline emission always produces the same key, so it renders once. */
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

  // -- websocket ------------------------------------------------------------

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
      try { msg = JSON.parse(e.data); } catch { return; }
      this._emit(msg);
    };

    ws.onerror = () => { try { ws.close(); } catch { /* noop */ } };

    ws.onclose = () => {
      if (this.settled || this.closedByUs) { this.onState?.("closed"); return; }
      // The run is still going: the server closes only on a terminal stage,
      // so an early close is a transport problem. Reconnect — the replay on
      // the new connection covers whatever we missed while disconnected.
      this._retry();
    };
  }

  _retry() {
    if (this.settled || this.closedByUs) return;
    // Poll while we are not connected so progress keeps flowing during backoff.
    this._startPolling();
    if (this.attempt >= this.maxAttempts) {
      this.onState?.("polling");
      return;
    }
    const delay = Math.min(1000 * 2 ** this.attempt, 15000);
    this.attempt += 1;
    setTimeout(() => { if (!this.closedByUs && !this.settled) this._open(); }, delay);
  }

  // -- polling fallback -----------------------------------------------------

  /** Replays the backend's own recorded stages; it never invents one. */
  _startPolling() {
    if (this.pollTimer || !this.runId || this.settled) return;
    const tick = async () => {
      if (this.settled || this.closedByUs) return;
      try {
        const data = await api.runStatus(this.runId);
        (data.progress || []).forEach((m) => this._emit({ ...m, polled: true }));
        if (data.status && data.status !== "running") this._settle(data);
      } catch { /* transient — keep polling */ }
    };
    this.pollTimer = setInterval(tick, POLL_INTERVAL_MS);
    tick();
  }

  _stopPolling() {
    if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
  }

  // -- completion -----------------------------------------------------------

  /** Resolve the run exactly once, fetching the authoritative final result.
   *  Retries briefly because the terminal stage and the stored result are
   *  written by the same task but observed over different transports. */
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
      }
      if (data && data.status && data.status !== "running" && data.result) break;
      await sleep(SETTLE_DELAY_MS);
    }

    this.close();

    if (!data || !data.result) {
      this.onError?.(new Error(
        "Run finished but the backend returned no result document."));
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
    try { this.ws?.close(); } catch { /* noop */ }
    this.ws = null;
  }
}
