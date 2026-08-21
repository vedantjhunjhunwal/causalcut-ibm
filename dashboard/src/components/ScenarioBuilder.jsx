import { useMemo, useRef, useState } from "react";
import { api } from "../api";
import { Upload, Play, CheckCircle2, AlertTriangle, Download, Trash2, Layers, Cpu } from "lucide-react";

// Entity editors
const ENTITY_TABS = [
  {
    key: "zones",
    label: "Zones",
    singular: "zone",
    fields: [
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "name", t: "text", ph: "Coke Oven" },
      {
        k: "hazard_class",
        t: "select",
        opts: ["standard", "gas_hazard", "high_risk", "rotating_equipment", "propagation", "admin"],
      },
      { k: "baseline_gas_threshold_ppm", t: "number", def: 200 },
      { k: "ventilation_status", t: "select", opts: ["nominal", "degraded", "failed"] },
      { k: "ventilation_flow_ratio", t: "number", def: 1.0, step: 0.05 },
    ],
  },
  {
    key: "zone_adjacency",
    label: "Adjacency",
    singular: "link",
    fields: [
      { k: "zone_a", t: "text", ph: "zone-1", req: true },
      { k: "zone_b", t: "text", ph: "zone-4", req: true },
      {
        k: "medium",
        t: "select",
        opts: ["ventilation_duct", "shared_duct", "utility_bus", "doorway", "shared_utility"],
      },
    ],
  },
  {
    key: "sensors",
    label: "Sensors",
    singular: "sensor",
    fields: [
      { k: "sensor_id", t: "text", ph: "GS-03", req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "modality", t: "select", opts: ["gas", "airflow", "temperature", "vibration"] },
      { k: "unit", t: "text", ph: "ppm" },
    ],
  },
  {
    key: "assets",
    label: "Assets",
    singular: "asset",
    fields: [
      { k: "asset_id", t: "text", ph: "LATHE-01", req: true },
      { k: "zone_id", t: "text", ph: "zone-3", req: true },
      { k: "asset_type", t: "text", ph: "lathe" },
      { k: "failure_probability", t: "number", def: 0, step: 0.05 },
      { k: "condition", t: "text", ph: "nominal" },
    ],
  },
  {
    key: "gas_readings",
    label: "Gas Readings",
    singular: "reading",
    fields: [
      { k: "sensor_id", t: "text", ph: "GS-03", req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      {
        k: "gas_type",
        t: "select",
        opts: ["ammonia", "carbon_monoxide", "methane", "ethylene", "toluene", "acetone"],
      },
      { k: "concentration_ppm", t: "number", def: 0, req: true },
      { k: "severity", t: "number", def: 0, step: 0.05 },
      { k: "confidence", t: "number", def: 1, step: 0.05 },
      { k: "offset_seconds", t: "number", def: 0 },
      { k: "features", t: "features", ph: "paste 128 comma-separated sensor values" },
    ],
  },
  {
    key: "machine_readings",
    label: "Machine (AI4I)",
    singular: "machine reading",
    fields: [
      { k: "asset_id", t: "text", ph: "M-1", req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "Type", t: "select", opts: ["L", "M", "H"] },
      { k: "Air_temperature", t: "number", def: 298.1, step: 0.1 },
      { k: "Process_temperature", t: "number", def: 308.6, step: 0.1 },
      { k: "Rotational_speed", t: "number", def: 1500 },
      { k: "Torque", t: "number", def: 40, step: 0.1 },
      { k: "Tool_wear", t: "number", def: 0 },
    ],
  },
  {
    key: "hydraulic_readings",
    label: "Hydraulic",
    singular: "hydraulic reading",
    fields: [
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      {
        k: "sensor_data",
        t: "hydraulic_sensors",
        ph: 'Paste JSON: {"PS1": [...], "PS2": [...], ...} — 17 sensors required',
      },
      { k: "offset_seconds", t: "number", def: 0 },
    ],
  },
  {
    key: "workers",
    label: "Workers",
    singular: "worker",
    fields: [
      { k: "worker_id", t: "text", ph: "W-003", req: true },
      { k: "zone_id", t: "text", ph: "zone-1" },
      { k: "present", t: "bool", def: true },
      { k: "missing_ppe", t: "csv", ph: "hard_hat, gloves" },
    ],
  },
  {
    key: "permits",
    label: "Permits",
    singular: "permit",
    fields: [
      { k: "permit_id", t: "text", ph: "PTW-007", req: true },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      {
        k: "permit_type",
        t: "select",
        opts: [
          "hot_work",
          "confined_space",
          "electrical_isolation",
          "mechanical",
          "loto",
          "working_at_height",
        ],
      },
      { k: "status", t: "select", opts: ["active", "suspended", "closed", "expired"] },
      { k: "worker_id", t: "text", ph: "W-001" },
    ],
  },
  {
    key: "events",
    label: "Timeline Events",
    singular: "event",
    fields: [
      {
        k: "event_type",
        t: "select",
        opts: [
          "gas_anomaly",
          "ppe_violation",
          "worker_presence",
          "permit_status",
          "utility_condition",
          "equipment_failure",
          "barrier_status",
        ],
        req: true,
      },
      { k: "zone_id", t: "text", ph: "zone-1", req: true },
      { k: "offset_seconds", t: "number", def: 0 },
      { k: "severity", t: "number", def: 0, step: 0.05 },
      { k: "confidence", t: "number", def: 1, step: 0.05 },
      { k: "information_class", t: "select", opts: ["M", "P", "S", "C", "R", "H"] },
      { k: "label", t: "text", ph: "gas spike" },
    ],
  },
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
  zones: [],
  zone_adjacency: [],
  sensors: [],
  assets: [],
  gas_readings: [],
  machine_readings: [],
  hydraulic_readings: [],
  vision_inputs: [],
  tracking_inputs: [],
  workers: [],
  permits: [],
  events: [],
  metadata: {},
};

export default function ScenarioBuilder({ scenario, setScenario, onRun, busy }) {
  const [tab, setTab] = useState("meta");
  const [errors, setErrors] = useState({});
  const [banner, setBanner] = useState(null);
  const fileRef = useRef(null);

  const errorFor = (path) => errors[path];

  const update = (patch) => setScenario((s) => ({ ...s, ...patch }));

  const updateEntity = (key, idx, fieldName, value) =>
    setScenario((s) => {
      const list = [...(s[key] || [])];
      list[idx] = { ...list[idx], [fieldName]: value };
      return { ...s, [key]: list };
    });

  const addEntity = (cfg) =>
    setScenario((s) => ({ ...s, [cfg.key]: [...(s[cfg.key] || []), blankEntity(cfg)] }));

  const removeEntity = (key, idx) =>
    setScenario((s) => ({ ...s, [key]: (s[key] || []).filter((_, i) => i !== idx) }));

  const applyErrors = (errList) => {
    const map = {};
    (errList || []).forEach((e) => {
      map[e.field] = e.message;
    });
    setErrors(map);
    return map;
  };

  const doValidate = async () => {
    setBanner(null);
    try {
      const res = await api.validate(scenario);
      if (res.valid) {
        setErrors({});
        setBanner({
          ok: true,
          msg: `Valid ✓ ${res.event_count} canonical event(s) will be generated.`,
        });
      } else {
        applyErrors(res.errors);
        setBanner({
          ok: false,
          msg: `${res.errors.length} validation error(s). See highlighted fields.`,
        });
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
      const first = res.errors[0]?.field?.split(".")[0];
      if (first && ENTITY_TABS.some((t) => t.key === first)) setTab(first);
    }
  };

  const onUpload = (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const parsed = JSON.parse(reader.result);
        const target = parsed.scenario && typeof parsed.scenario === "object" ? parsed.scenario : parsed;
        const newScn = {
          ...EMPTY_SCENARIO,
          ...target,
          name: target.name || target.scenario_id || file.name.replace(/\.json$/i, ""),
        };
        setScenario(newScn);
        setErrors({});
        setBanner({
          ok: true,
          msg: `Loaded "${newScn.name}" (${(newScn.zones || []).length} zones, ${(newScn.sensors || []).length} sensors, ${(newScn.workers || []).length} workers). Ready to run!`,
          showRunButton: true,
        });
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
      setBanner({
        ok: true,
        msg: `Loaded sample "${s.name}". Ready to simulate!`,
        showRunButton: true,
      });
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
    try {
      const tpl = await api.template();
      const blob = new Blob([JSON.stringify(tpl, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "scenario_template.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      const blob = new Blob([JSON.stringify(scenario, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${scenario.name || "scenario"}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  const summary = useMemo(() => {
    const c = (k) => (scenario[k] || []).length;
    return `${c("zones")} zones · ${c("sensors")} sensors · ${c("workers")} workers · ${c("permits")} permits · ${c("gas_readings")} gas · ${c("machine_readings")} machine · ${c("events")} events`;
  }, [scenario]);

  const field = (cfg, key, idx, f) => {
    const path = `${key}.${idx}.${f.k}`;
    const err = errorFor(path);
    const val = scenario[key]?.[idx]?.[f.k];
    const common = {
      style: {
        width: "100%",
        padding: "6px 10px",
        fontSize: 12,
        borderRadius: 4,
        border: err ? "1px solid #ef4444" : "1px solid #cbd5e1",
        backgroundColor: "#ffffff",
        boxSizing: "border-box",
      },
    };

    let input;
    if (f.t === "select") {
      input = (
        <select
          {...common}
          value={val ?? ""}
          onChange={(e) => updateEntity(key, idx, f.k, e.target.value)}
        >
          {f.opts.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    } else if (f.t === "bool") {
      input = (
        <select
          {...common}
          value={String(val)}
          onChange={(e) => updateEntity(key, idx, f.k, e.target.value === "true")}
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      );
    } else if (f.t === "csv") {
      input = (
        <input
          {...common}
          placeholder={f.ph}
          value={Array.isArray(val) ? val.join(", ") : val}
          onChange={(e) =>
            updateEntity(
              key,
              idx,
              f.k,
              e.target.value.split(",").map((x) => x.trim()).filter(Boolean)
            )
          }
        />
      );
    } else if (f.t === "features") {
      const n = Array.isArray(val) ? val.length : 0;
      input = (
        <div>
          <textarea
            rows={2}
            placeholder={f.ph}
            style={{ ...common.style, fontFamily: "var(--font-mono)", fontSize: 11 }}
            value={Array.isArray(val) ? val.join(",") : ""}
            onChange={(e) => {
              const txt = e.target.value.trim();
              if (!txt) return updateEntity(key, idx, f.k, null);
              const arr = txt.split(/[,\s]+/).map(Number).filter((x) => !Number.isNaN(x));
              updateEntity(key, idx, f.k, arr);
            }}
          />
          <div style={{ fontSize: 10, marginTop: 3, color: n === 128 ? "#059669" : "#64748b" }}>
            {n === 0 ? "optional — 128 raw values for XGBoost gas model" : `${n}/128 values loaded`}
          </div>
        </div>
      );
    } else if (f.t === "number") {
      input = (
        <input
          {...common}
          type="number"
          step={f.step ?? 1}
          value={val ?? 0}
          onChange={(e) =>
            updateEntity(key, idx, f.k, e.target.value === "" ? "" : Number(e.target.value))
          }
        />
      );
    } else {
      input = (
        <input
          {...common}
          placeholder={f.ph}
          value={val ?? ""}
          onChange={(e) => updateEntity(key, idx, f.k, e.target.value)}
        />
      );
    }
    return (
      <div key={f.k} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: "#475569", textTransform: "uppercase" }}>
          {f.k} {f.req ? "*" : ""}
        </span>
        {input}
        {err && <div style={{ fontSize: 10, color: "#ef4444" }}>{err}</div>}
      </div>
    );
  };

  const activeCfg = ENTITY_TABS.find((t) => t.key === tab);

  return (
    <div className="panel-box" style={{ padding: 20 }}>
      {/* Action Bar */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
        <button className="action-btn primary" onClick={() => fileRef.current?.click()}>
          <Upload size={14} />
          <span>Upload JSON</span>
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json"
          onChange={onUpload}
          style={{ display: "none" }}
        />

        <button className="action-btn" onClick={() => loadSample("coke_oven_scenario")}>
          Load Coke-Oven Sample
        </button>
        <button className="action-btn" onClick={() => loadSample("simple_gas_leak")}>
          Load Gas Leak Sample
        </button>
        <button className="action-btn" onClick={downloadTemplate}>
          <Download size={14} />
          <span>Download JSON</span>
        </button>
        <button className="action-btn" onClick={clearAll} style={{ color: "#b91c1c" }}>
          <Trash2 size={14} />
          <span>Clear</span>
        </button>
      </div>

      {banner && (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 16px",
            borderRadius: 4,
            fontSize: 12.5,
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            backgroundColor: banner.ok ? "#ecfdf5" : "#fef2f2",
            color: banner.ok ? "#047857" : "#b91c1c",
            border: `1px solid ${banner.ok ? "#a7f3d0" : "#fecaca"}`,
          }}
        >
          <span>{banner.msg}</span>
          {banner.showRunButton && (
            <button
              className="action-btn primary"
              style={{ padding: "4px 10px", fontSize: 11 }}
              onClick={handleRun}
              disabled={busy}
            >
              <Play size={12} fill="#ffffff" />
              <span>▶ Run Now</span>
            </button>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="filter-pills-row" style={{ marginBottom: 16 }}>
        <button
          className={`filter-pill ${tab === "meta" ? "active" : ""}`}
          onClick={() => setTab("meta")}
        >
          Meta Properties
        </button>
        {ENTITY_TABS.map((t) => (
          <button
            key={t.key}
            className={`filter-pill ${tab === t.key ? "active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label} ({(scenario[t.key] || []).length})
          </button>
        ))}
      </div>

      {tab === "meta" ? (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", display: "block", marginBottom: 4 }}>
              Scenario Name *
            </label>
            <input
              style={{ width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: 4, border: "1px solid #cbd5e1" }}
              placeholder="e.g. Coke Oven Flash-Fire"
              value={scenario.name || ""}
              onChange={(e) => update({ name: e.target.value })}
            />
          </div>

          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", display: "block", marginBottom: 4 }}>
              Factory Identifier
            </label>
            <input
              style={{ width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: 4, border: "1px solid #cbd5e1" }}
              value={scenario.factory_id || "steelforge-001"}
              onChange={(e) => update({ factory_id: e.target.value })}
            />
          </div>

          <div style={{ gridColumn: "1 / -1" }}>
            <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", display: "block", marginBottom: 4 }}>
              Incident Description
            </label>
            <textarea
              rows={2}
              style={{ width: "100%", padding: "7px 10px", fontSize: 12.5, borderRadius: 4, border: "1px solid #cbd5e1" }}
              value={scenario.description || ""}
              onChange={(e) => update({ description: e.target.value })}
            />
          </div>

          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", display: "block", marginBottom: 4 }}>
              Safety Threshold (Residual Target)
            </label>
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              style={{ width: "100%", padding: "7px 10px", fontSize: 13, borderRadius: 4, border: "1px solid #cbd5e1" }}
              value={scenario.safety_threshold ?? 0.15}
              onChange={(e) => update({ safety_threshold: Number(e.target.value) })}
            />
          </div>

          <div style={{ alignSelf: "center", color: "#64748b", fontFamily: "var(--font-mono)", fontSize: 11 }}>
            {summary}
          </div>
        </div>
      ) : (
        <div>
          {(scenario[activeCfg.key] || []).map((_, idx) => (
            <div
              key={idx}
              style={{
                display: "grid",
                gridTemplateColumns: `repeat(${Math.min(activeCfg.fields.length, 3)}, 1fr) auto`,
                gap: 12,
                alignItems: "end",
                backgroundColor: "#f8fafc",
                padding: 12,
                borderRadius: 4,
                border: "1px solid #e2e8f0",
                marginBottom: 10,
              }}
            >
              {activeCfg.fields.map((f) => field(activeCfg, activeCfg.key, idx, f))}
              <button
                className="action-btn"
                style={{ padding: "6px 10px", color: "#b91c1c", borderColor: "#fca5a5" }}
                onClick={() => removeEntity(activeCfg.key, idx)}
              >
                Remove
              </button>
            </div>
          ))}

          {(scenario[activeCfg.key] || []).length === 0 && (
            <div style={{ padding: "16px 0", color: "#94a3b8", fontSize: 12, fontFamily: "var(--font-mono)" }}>
              No {activeCfg.label.toLowerCase()} configured yet.
            </div>
          )}

          <button
            className="action-btn"
            style={{ marginTop: 8 }}
            onClick={() => addEntity(activeCfg)}
          >
            + Add {activeCfg.singular}
          </button>
        </div>
      )}

      {/* Footer Controls */}
      <div
        style={{
          marginTop: 20,
          borderTop: "1px solid #e2e8f0",
          paddingTop: 16,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <button className="action-btn" onClick={doValidate} disabled={busy}>
          Validate Schema
        </button>
        <button
          className="action-btn primary"
          style={{ padding: "8px 20px", fontSize: 13, fontWeight: 700 }}
          onClick={handleRun}
          disabled={busy || !scenario.name || (scenario.zones || []).length === 0}
        >
          <Play size={14} fill="#ffffff" />
          <span>{busy ? "Running Pipeline…" : "▶ Run Scenario"}</span>
        </button>
      </div>
    </div>
  );
}
