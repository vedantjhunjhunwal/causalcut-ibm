import { useMemo, useRef, useState } from "react";
import { api } from "../api";

// Entity editors are data-driven: each config declares its fields, so adding a
// field or entity type stays declarative rather than hand-written JSX per row.
const ENTITY_TABS = [
  { key: "zones", label: "Zones", singular: "zone",
    fields: [
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "name", t: "text", ph: "Coke Oven" },
      { k: "hazard_class", t: "select", opts: ["standard", "gas_hazard", "high_risk", "rotating_equipment", "propagation", "admin"] },
      { k: "baseline_gas_threshold_ppm", t: "number", def: 200 },
      { k: "ventilation_status", t: "select", opts: ["nominal", "degraded", "failed"] },
      { k: "ventilation_flow_ratio", t: "number", def: 1.0, step: 0.05 },
    ] },
  { key: "zone_adjacency", label: "Adjacency", singular: "link",
    fields: [
      { k: "zone_a", t: "text", ph: "zone-1", req: true },
      { k: "zone_b", t: "text", ph: "zone-4", req: true },
      { k: "medium", t: "select", opts: ["ventilation_duct", "shared_duct", "utility_bus", "doorway", "shared_utility"] },
    ] },
  { key: "sensors", label: "Sensors", singular: "sensor",
    fields: [
      { k: "sensor_id", t: "text", ph: "GS-03", req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "modality", t: "select", opts: ["gas", "airflow", "temperature", "vibration"] },
      { k: "unit", t: "text", ph: "ppm" },
    ] },
  { key: "assets", label: "Assets", singular: "asset",
    fields: [
      { k: "asset_id", t: "text", ph: "LATHE-01", req: true },
      { k: "zone_id", t: "text", ph: "zone-3", req: true },
      { k: "asset_type", t: "text", ph: "lathe" },
      { k: "failure_probability", t: "number", def: 0, step: 0.05 },
      { k: "condition", t: "text", ph: "nominal" },
    ] },
  { key: "gas_readings", label: "Gas Readings", singular: "reading",
    fields: [
      { k: "sensor_id", t: "text", ph: "GS-03", req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "gas_type", t: "select", opts: ["ammonia", "carbon_monoxide", "methane", "ethylene", "toluene", "acetone"] },
      { k: "concentration_ppm", t: "number", def: 0, req: true },
      { k: "severity", t: "number", def: 0, step: 0.05 },
      { k: "confidence", t: "number", def: 1, step: 0.05 },
      { k: "offset_seconds", t: "number", def: 0 },
      { k: "features", t: "features", ph: "paste 128 comma-separated sensor values" },
    ] },
  { key: "machine_readings", label: "Machine (AI4I)", singular: "machine reading",
    fields: [
      { k: "asset_id", t: "text", ph: "M-1", req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "Type", t: "select", opts: ["L", "M", "H"] },
      { k: "Air_temperature", t: "number", def: 298.1, step: 0.1 },
      { k: "Process_temperature", t: "number", def: 308.6, step: 0.1 },
      { k: "Rotational_speed", t: "number", def: 1500 },
      { k: "Torque", t: "number", def: 40, step: 0.1 },
      { k: "Tool_wear", t: "number", def: 0 },
    ] },
  { key: "hydraulic_readings", label: "Hydraulic", singular: "hydraulic reading",
    fields: [
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "sensor_data", t: "hydraulic_sensors", ph: "Paste JSON: {\"PS1\": [...], \"PS2\": [...], ...} — 17 sensors required" },
      { k: "offset_seconds", t: "number", def: 0 },
    ] },
  { key: "workers", label: "Workers", singular: "worker",
    fields: [
      { k: "worker_id", t: "text", ph: "W-003", req: true },
      { k: "zone_id", t: "text", ph: "zone-1" },
      { k: "present", t: "bool", def: true },
      { k: "missing_ppe", t: "csv", ph: "hard_hat, gloves" },
    ] },
  { key: "permits", label: "Permits", singular: "permit",
    fields: [
      { k: "permit_id", t: "text", ph: "PTW-007", req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "permit_type", t: "select", opts: ["hot_work", "confined_space", "electrical_isolation", "mechanical", "loto", "working_at_height"] },
      { k: "status", t: "select", opts: ["active", "suspended", "closed", "expired"] },
      { k: "worker_id", t: "text", ph: "W-001" },
    ] },
  { key: "events", label: "Timeline Events", singular: "event",
    fields: [
      { k: "event_type", t: "select", opts: ["gas_anomaly", "ppe_violation", "worker_presence", "permit_status", "utility_condition", "equipment_failure", "barrier_status"], req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "offset_seconds", t: "number", def: 0 },
      { k: "severity", t: "number", def: 0, step: 0.05 },
      { k: "confidence", t: "number", def: 1, step: 0.05 },
      { k: "information_class", t: "select", opts: ["M", "P", "S", "C", "R", "H"] },
      { k: "label", t: "text", ph: "gas spike" },
    ] },
];

function blankEntity(cfg) {
  const o = {};
  cfg.fields.forEach((f) => {
    if (f.t === "features" || f.t === "hydraulic_sensors") o[f.k] = null;
    else if (f.t === "bool") o[f.k] = f.def ?? false;
    else if (f.t === "csv") o[f.k] = [];
    else if (f.t === "number") o[f.k] = f.def ?? 0;
    else if (f.t === "select") o[f.k] = f.opts[0];
    else o[f.k] = "";
  });
  return o;
}

export const EMPTY_SCENARIO = {
  name: "",
  description: "",
  factory_id: "steelforge-001",
  safety_threshold: 0.15,
  zones: [], zone_adjacency: [], sensors: [], assets: [],
  gas_readings: [], machine_readings: [], hydraulic_readings: [],
  // Populated from the Raw Model Inputs panel. They travel with the scenario
  // and are executed by the shared vision / tracking services during the run.
  vision_inputs: [], tracking_inputs: [],
  workers: [], permits: [], events: [],
  metadata: {},
};

export default function ScenarioBuilder({ scenario, setScenario, onRun, busy }) {
  const [tab, setTab] = useState("meta");
  const [errors, setErrors] = useState({}); // path -> message
  const [banner, setBanner] = useState(null);
  const fileRef = useRef(null);

  const errorFor = (path) => errors[path];

  const update = (patch) => setScenario((s) => ({ ...s, ...patch }));

  const updateEntity = (key, idx, field, value) =>
    setScenario((s) => {
      const list = [...(s[key] || [])];
      list[idx] = { ...list[idx], [field]: value };
      return { ...s, [key]: list };
    });

  const addEntity = (cfg) =>
    setScenario((s) => ({ ...s, [cfg.key]: [...(s[cfg.key] || []), blankEntity(cfg)] }));

  const removeEntity = (key, idx) =>
    setScenario((s) => ({ ...s, [key]: (s[key] || []).filter((_, i) => i !== idx) }));

  const applyErrors = (errList) => {
    const map = {};
    (errList || []).forEach((e) => { map[e.field] = e.message; });
    setErrors(map);
    return map;
  };

  const doValidate = async () => {
    setBanner(null);
    try {
      const res = await api.validate(scenario);
      if (res.valid) {
        setErrors({});
        setBanner({ ok: true, msg: `Valid ✓  ${res.event_count} canonical event(s) will be generated.` });
      } else {
        applyErrors(res.errors);
        setBanner({ ok: false, msg: `${res.errors.length} validation error(s). See highlighted fields.` });
      }
    } catch (e) {
      setBanner({ ok: false, msg: `Validation request failed: ${e.message}` });
    }
  };

  const handleRun = async () => {
    const res = await onRun(scenario);
    if (res && res.errors) {
      applyErrors(res.errors);
      setBanner({ ok: false, msg: `Cannot run: ${res.errors.length} validation error(s).` });
      // jump to the first tab that has an error
      const first = res.errors[0]?.field?.split(".")[0];
      if (first && ENTITY_TABS.some((t) => t.key === first)) setTab(first);
    }
  };

  const onUpload = (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(reader.result);
        setScenario({ ...EMPTY_SCENARIO, ...parsed });
        setErrors({});
        setBanner({ ok: true, msg: `Loaded "${parsed.name || file.name}" from JSON. Review & edit before running.` });
        setTab("meta");
      } catch (e) {
        setBanner({ ok: false, msg: `Invalid JSON: ${e.message}` });
      }
    };
    reader.readAsText(file);
    ev.target.value = "";
  };

  const loadSample = async (name) => {
    try {
      const s = await api.sample(name);
      setScenario({ ...EMPTY_SCENARIO, ...s });
      setErrors({});
      setBanner({ ok: true, msg: `Loaded sample "${s.name}". This is a starting point — edit freely.` });
      setTab("meta");
    } catch (e) {
      setBanner({ ok: false, msg: `Could not load sample: ${e.message}` });
    }
  };

  const clearAll = () => {
    setScenario({ ...EMPTY_SCENARIO });
    setErrors({});
    setBanner({ ok: true, msg: "Scenario cleared." });
    setTab("meta");
  };

  const downloadTemplate = async () => {
    const tpl = await api.template();
    const blob = new Blob([JSON.stringify(tpl, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "scenario_template.json"; a.click();
    URL.revokeObjectURL(url);
  };

  const summary = useMemo(() => {
    const c = (k) => (scenario[k] || []).length;
    return `${c("zones")} zones · ${c("sensors")} sensors · ${c("workers")} workers · ${c("permits")} permits · ${c("gas_readings")} gas · ${c("hydraulic_readings")} hydraulic · ${c("vision_inputs")} frames · ${c("tracking_inputs")} tracking · ${c("events")} events`;
  }, [scenario]);

  const field = (cfg, key, idx, f) => {
    const path = `${key}.${idx}.${f.k}`;
    const err = errorFor(path);
    const val = scenario[key][idx][f.k];
    const common = { className: err ? "err" : "" };
    let input;
    if (f.t === "select") {
      input = (
        <select {...common} value={val ?? ""} onChange={(e) => updateEntity(key, idx, f.k, e.target.value)}>
          {f.opts.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    } else if (f.t === "bool") {
      input = (
        <select {...common} value={String(val)} onChange={(e) => updateEntity(key, idx, f.k, e.target.value === "true")}>
          <option value="true">true</option><option value="false">false</option>
        </select>
      );
    } else if (f.t === "csv") {
      input = (
        <input {...common} placeholder={f.ph} value={Array.isArray(val) ? val.join(", ") : val}
          onChange={(e) => updateEntity(key, idx, f.k, e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />
      );
    } else if (f.t === "features") {
      const n = Array.isArray(val) ? val.length : 0;
      input = (
        <div>
          <textarea rows={2} placeholder={f.ph}
            value={Array.isArray(val) ? val.join(",") : ""}
            onChange={(e) => {
              const txt = e.target.value.trim();
              if (!txt) return updateEntity(key, idx, f.k, null);
              const arr = txt.split(/[,\s]+/).map(Number).filter((x) => !Number.isNaN(x));
              updateEntity(key, idx, f.k, arr);
            }} />
          <div className={n === 0 || n === 128 ? "faint" : "err-msg"} style={{ fontSize: 10, marginTop: 3 }}>
            {n === 0
              ? "optional — supply 128 raw values to run the TRAINED gas model"
              : `${n}/128 values ${n === 128 ? "✓ model inference will run" : "— must be exactly 128"}`}
          </div>
        </div>
      );
    } else if (f.t === "hydraulic_sensors") {
      const isObj = typeof val === "object" && val !== null;
      const displayVal = isObj ? JSON.stringify(val) : (val || "");
      const n = isObj ? Object.keys(val).length : 0;
      input = (
        <div>
          <textarea rows={2} placeholder={f.ph}
            value={displayVal}
            onChange={(e) => {
              const txt = e.target.value.trim();
              if (!txt) return updateEntity(key, idx, f.k, null);
              try {
                const parsed = JSON.parse(txt);
                updateEntity(key, idx, f.k, parsed);
              } catch {
                updateEntity(key, idx, f.k, txt);
              }
            }} />
          <div className={n === 17 ? "faint" : "err-msg"} style={{ fontSize: 10, marginTop: 3 }}>
            {n === 0
              ? "Paste JSON: {\"PS1\": [...], \"PS2\": [...], ...} — 17 sensors required"
              : `${n}/17 sensors ${n === 17 ? "✓ model inference will run" : "— requires 17"}`}
          </div>
        </div>
      );
    } else if (f.t === "number") {
      input = (
        <input {...common} type="number" step={f.step ?? 1} value={val ?? 0}
          onChange={(e) => updateEntity(key, idx, f.k, e.target.value === "" ? "" : Number(e.target.value))} />
      );
    } else {
      input = (
        <input {...common} placeholder={f.ph} value={val ?? ""}
          onChange={(e) => updateEntity(key, idx, f.k, e.target.value)} />
      );
    }
    return (
      <label className="field" key={f.k}>
        <span>{f.k}{f.req ? " *" : ""}</span>
        {input}
        {err && <div className="err-msg">{err}</div>}
      </label>
    );
  };

  const activeCfg = ENTITY_TABS.find((t) => t.key === tab);

  return (
    <div className="panel">
      <div className="panel-title">Scenario Setup</div>

      <div className="btn-row" style={{ marginBottom: 14 }}>
        <button className="btn" onClick={() => fileRef.current?.click()}>⭱ Upload JSON</button>
        <input ref={fileRef} type="file" accept="application/json" onChange={onUpload} style={{ display: "none" }} />
        <button className="btn" onClick={() => loadSample("coke_oven_scenario")}>Load Coke-Oven sample</button>
        <button className="btn" onClick={() => loadSample("simple_gas_leak")}>Load simple sample</button>
        <button className="btn ghost" onClick={downloadTemplate}>Download template</button>
        <button className="btn ghost" onClick={clearAll}>Clear</button>
      </div>

      {banner && (
        <div className={banner.ok ? "audit-ok" : "warn"} style={{ marginBottom: 14 }}>{banner.msg}</div>
      )}

      <div className="tabs">
        <span className={`tab ${tab === "meta" ? "active" : ""}`} onClick={() => setTab("meta")}>Meta</span>
        {ENTITY_TABS.map((t) => (
          <span key={t.key} className={`tab ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
            {t.label} ({(scenario[t.key] || []).length})
          </span>
        ))}
      </div>

      {tab === "meta" ? (
        <div className="grid cols-2">
          <label className="field">
            <span>name *</span>
            <input className={errorFor("name") ? "err" : ""} placeholder="Coke Oven Flash-Fire"
              value={scenario.name} onChange={(e) => update({ name: e.target.value })} />
            {errorFor("name") && <div className="err-msg">{errorFor("name")}</div>}
          </label>
          <label className="field">
            <span>factory_id</span>
            <input value={scenario.factory_id} onChange={(e) => update({ factory_id: e.target.value })} />
          </label>
          <label className="field" style={{ gridColumn: "1 / -1" }}>
            <span>description</span>
            <textarea rows={2} value={scenario.description} onChange={(e) => update({ description: e.target.value })} />
          </label>
          <label className="field">
            <span>safety_threshold (residual-risk target)</span>
            <input type="number" step="0.01" min="0" max="1" value={scenario.safety_threshold}
              onChange={(e) => update({ safety_threshold: Number(e.target.value) })} />
          </label>
          <div style={{ alignSelf: "center", color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11 }}>
            {summary}
          </div>
        </div>
      ) : (
        <div>
          {(scenario[activeCfg.key] || []).map((_, idx) => (
            <div className="entity-row" key={idx}
              style={{ gridTemplateColumns: `repeat(${Math.min(activeCfg.fields.length, 4)}, 1fr) auto` }}>
              {activeCfg.fields.map((f) => field(activeCfg, activeCfg.key, idx, f))}
              <button className="mini-btn rm" onClick={() => removeEntity(activeCfg.key, idx)}>remove</button>
            </div>
          ))}
          {(scenario[activeCfg.key] || []).length === 0 && (
            <div className="faint mono" style={{ fontSize: 12, padding: "8px 0" }}>
              no {activeCfg.label.toLowerCase()} yet
            </div>
          )}
          <button className="mini-btn" onClick={() => addEntity(activeCfg)}>+ add {activeCfg.singular}</button>
        </div>
      )}

      <div className="btn-row" style={{ marginTop: 18, borderTop: "1px solid var(--line)", paddingTop: 16 }}>
        <button className="btn" onClick={doValidate} disabled={busy}>Validate</button>
        <button className="btn primary" onClick={handleRun} disabled={busy || !scenario.name || (scenario.zones || []).length === 0}>
          {busy ? "Running…" : "▶ Run Scenario"}
        </button>
      </div>
    </div>
  );
}
