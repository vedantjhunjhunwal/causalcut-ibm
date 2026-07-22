import { useRef, useState } from "react";
import { API } from "../api";

// Raw model inputs. Nothing runs on page load — every call is user-initiated.
//
// Two distinct actions per tab, and the difference matters:
//
//   "Test inference"   — a one-off call to /models/... so the operator can see
//                        whether the checkpoint is loaded and what it returns.
//                        It is a side check; its output goes nowhere.
//   "Add to scenario"  — attaches the raw input to the scenario payload
//                        (hydraulic_readings / vision_inputs / tracking_inputs).
//                        On Run Scenario the backend invokes the SAME shared
//                        vision/tracking services, turns their real output into
//                        canonical events, and pushes them through the queue,
//                        SQLite state store, hypergraph and the rest of the
//                        CAUSALCUT pipeline alongside every other event.

const HYD_SENSORS = [
  ["PS1", "bar", "Pressure 1"], ["PS2", "bar", "Pressure 2"],
  ["PS3", "bar", "Pressure 3"], ["PS4", "bar", "Pressure 4"],
  ["PS5", "bar", "Pressure 5"], ["PS6", "bar", "Pressure 6"],
  ["EPS1", "W", "Motor power"], ["FS1", "l/min", "Volume flow 1"],
  ["FS2", "l/min", "Volume flow 2"], ["TS1", "°C", "Temperature 1"],
  ["TS2", "°C", "Temperature 2"], ["TS3", "°C", "Temperature 3"],
  ["TS4", "°C", "Temperature 4"], ["VS1", "mm/s", "Vibration"],
  ["CE", "%", "Cooling efficiency"], ["CP", "kW", "Cooling power"],
  ["SE", "%", "Efficiency factor"],
];

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const ALLOWED_IMAGE = ["image/jpeg", "image/png", "image/webp"];

// Mirrors the backend id pattern: ^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$
function safeId(raw, fallback) {
  const cleaned = String(raw || "")
    .replace(/\.[^.]+$/, "")          // drop file extension
    .replace(/[^A-Za-z0-9_.-]/g, "-")
    .replace(/^[^A-Za-z0-9]+/, "")
    .slice(0, 64);
  return cleaned || fallback;
}

function Result({ data }) {
  if (!data) return null;
  const degraded = data.inference_mode !== "real";
  return (
    <div className={degraded ? "warn" : "audit-ok"} style={{ marginTop: 10 }}>
      <div className="mono" style={{ fontSize: 11 }}>
        {data.model_name} · {data.model_version} · mode <b>{data.inference_mode}</b>
        {data.latency_ms != null && <> · {data.latency_ms} ms</>}
        {data.confidence != null && <> · conf {Number(data.confidence).toFixed(3)}</>}
      </div>
      {data.degraded_reason && (
        <div style={{ fontSize: 11, marginTop: 4 }}>⚠ {data.degraded_reason}</div>
      )}
      {data.prediction != null && (
        <pre style={{ fontSize: 10, marginTop: 6, maxHeight: 160, overflow: "auto" }}>
          {JSON.stringify(data.prediction, null, 1)}
        </pre>
      )}
    </div>
  );
}

/** The inputs already attached to the scenario for one modality. */
function Attached({ label, items, describe, onRemove }) {
  return (
    <div style={{ marginTop: 12 }}>
      <div className="mono" style={{ fontSize: 11, color: "var(--ink-dim)", marginBottom: 6 }}>
        In scenario: {items.length} {label}{items.length === 1 ? "" : "s"}
      </div>
      {items.length === 0 ? (
        <div className="faint mono" style={{ fontSize: 11 }}>
          none attached — this modality will not run in the pipeline.
        </div>
      ) : (
        items.map((it, i) => (
          <div className="entity-row" key={i}
               style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="mono" style={{ fontSize: 11, flex: 1 }}>{describe(it)}</span>
            <button className="mini-btn" onClick={() => onRemove(i)}>remove</button>
          </div>
        ))
      )}
    </div>
  );
}

export default function ModelInputPanel({ scenario, setScenario }) {
  const [tab, setTab] = useState("hydraulic");
  const [busy, setBusy] = useState(false);

  // Every attachment needs a zone that exists in the scenario, otherwise the
  // backend's referential-integrity check rejects the whole payload.
  const zoneIds = (scenario.zones || []).map((z) => z.zone_id).filter(Boolean);
  const [zone, setZone] = useState("");
  const activeZone = zoneIds.includes(zone) ? zone : (zoneIds[0] || "");

  const attach = (key, entry) =>
    setScenario((s) => ({ ...s, [key]: [...(s[key] || []), entry] }));

  const detach = (key, idx) =>
    setScenario((s) => ({ ...s, [key]: (s[key] || []).filter((_, i) => i !== idx) }));

  const requireZone = (setErr) => {
    if (!activeZone) {
      setErr("Add a zone to the scenario first — every model input must be "
             + "attached to a zone.");
      return false;
    }
    return true;
  };

  // ---- hydraulic ----
  const [cycles, setCycles] = useState(() =>
    Object.fromEntries(HYD_SENSORS.map(([s]) => [s, ""]))
  );
  const [hydErr, setHydErr] = useState(null);
  const [hydRes, setHydRes] = useState(null);

  const parseCycle = (txt) =>
    txt.split(/[,\s]+/).map(Number).filter((n) => !Number.isNaN(n));

  const hydraulicPayload = () => {
    const sensor_data = {};
    const missing = [];
    for (const [s] of HYD_SENSORS) {
      const arr = parseCycle(cycles[s] || "");
      if (arr.length === 0) missing.push(s);
      else sensor_data[s] = arr;
    }
    return { sensor_data, missing };
  };

  const submitHydraulic = async () => {
    const { sensor_data, missing } = hydraulicPayload();
    if (missing.length) {
      setHydErr(`Missing cycle data for ${missing.length} sensor(s): ${missing.join(", ")}`);
      return;
    }
    setHydErr(null); setBusy(true);
    try {
      const r = await fetch(`${API}/models/hydraulic/predict`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sensor_data }),
      });
      setHydRes(await r.json());
    } catch (e) { setHydErr(e.message); } finally { setBusy(false); }
  };

  const attachHydraulicToScenario = () => {
    const { sensor_data, missing } = hydraulicPayload();
    if (missing.length) { setHydErr(`Missing: ${missing.join(", ")}`); return; }
    if (!requireZone(setHydErr)) return;
    attach("hydraulic_readings",
           { zone_id: activeZone, sensor_data, offset_seconds: 0 });
    setHydErr(null);
  };

  const pasteHydraulicJson = (txt) => {
    try {
      const obj = JSON.parse(txt);
      const src = obj.sensor_data || obj;
      const next = { ...cycles };
      for (const [s] of HYD_SENSORS) if (Array.isArray(src[s])) next[s] = src[s].join(",");
      setCycles(next); setHydErr(null);
    } catch (e) { setHydErr(`Invalid JSON: ${e.message}`); }
  };

  // ---- vision ----
  const fileRef = useRef(null);
  const [preview, setPreview] = useState(null);
  const [imgErr, setImgErr] = useState(null);
  const [imgNote, setImgNote] = useState(null);
  const [visRes, setVisRes] = useState(null);
  const [imgB64, setImgB64] = useState(null);
  const [imgName, setImgName] = useState("");
  const [visWorker, setVisWorker] = useState("");
  const [visOffset, setVisOffset] = useState(0);

  const onImage = (ev) => {
    const f = ev.target.files?.[0];
    if (!f) return;
    if (!ALLOWED_IMAGE.includes(f.type)) {
      setImgErr(`Unsupported type "${f.type}". Allowed: JPEG, PNG, WebP.`);
      return;
    }
    if (f.size > MAX_IMAGE_BYTES) {
      setImgErr(`File is ${(f.size / 1e6).toFixed(1)} MB; limit is 8 MB.`);
      return;
    }
    setImgErr(null); setImgNote(null); setVisRes(null);
    setImgName(f.name);
    const reader = new FileReader();
    reader.onload = () => { setPreview(reader.result); setImgB64(String(reader.result).split(",")[1]); };
    reader.readAsDataURL(f);
  };

  const submitImage = async () => {
    if (!imgB64) { setImgErr("Choose an image first."); return; }
    setBusy(true);
    try {
      const r = await fetch(`${API}/models/vision/detect`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_ref: { format: "base64", data: imgB64 } }),
      });
      setVisRes(await r.json());
    } catch (e) { setImgErr(e.message); } finally { setBusy(false); }
  };

  const attachVisionToScenario = () => {
    if (!imgB64) { setImgErr("Choose an image first."); return; }
    if (!requireZone(setImgErr)) return;
    const used = new Set((scenario.vision_inputs || []).map((v) => v.image_id));
    let image_id = safeId(imgName, `frame-${(scenario.vision_inputs || []).length}`);
    let n = 1;
    while (used.has(image_id)) image_id = `${safeId(imgName, "frame")}-${n++}`.slice(0, 64);

    const entry = { zone_id: activeZone, image_id, image_b64: imgB64,
                    offset_seconds: Number(visOffset) || 0 };
    if (visWorker.trim()) entry.worker_id = visWorker.trim();
    attach("vision_inputs", entry);
    setImgErr(null);
    setImgNote(`Attached as "${image_id}" on ${activeZone}. It runs through the `
               + "YOLO PPE service as part of the scenario.");
  };

  // ---- tracking ----
  const [detText, setDetText] = useState(
    '[{"frame_id":1,"bbox":[100,120,60,140],"class":"person","confidence":0.91}]'
  );
  const [trkErr, setTrkErr] = useState(null);
  const [trkNote, setTrkNote] = useState(null);
  const [trkRes, setTrkRes] = useState(null);
  const [trkOffset, setTrkOffset] = useState(0);

  /** Validate and normalise to exactly the keys the Detection schema allows
   *  (it forbids extras), so a good paste is never rejected server-side. */
  const validateDetections = (txt) => {
    let arr;
    try { arr = JSON.parse(txt); }
    catch (e) { throw new Error(`Invalid JSON: ${e.message}`, { cause: e }); }
    if (!Array.isArray(arr)) throw new Error("Detections must be a JSON array.");
    return arr.map((d, i) => {
      if (!Array.isArray(d.bbox) || d.bbox.length !== 4)
        throw new Error(`Detection ${i}: bbox must be [x, y, w, h].`);
      if (d.bbox.some((n) => typeof n !== "number"))
        throw new Error(`Detection ${i}: bbox values must be numbers.`);
      if (typeof d.confidence !== "number" || d.confidence < 0 || d.confidence > 1)
        throw new Error(`Detection ${i}: confidence must be a number in [0, 1].`);
      if (!d.class) throw new Error(`Detection ${i}: "class" is required.`);
      if (d.frame_id == null) throw new Error(`Detection ${i}: "frame_id" is required.`);
      const out = { frame_id: d.frame_id, bbox: d.bbox, class: d.class,
                    confidence: d.confidence };
      if (d.track_id != null) out.track_id = d.track_id;
      return out;
    });
  };

  const submitTracking = async () => {
    let detections;
    try { detections = validateDetections(detText); setTrkErr(null); }
    catch (e) { setTrkErr(e.message); return; }
    setBusy(true);
    try {
      const r = await fetch(`${API}/models/tracking/update`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ detections }),
      });
      setTrkRes(await r.json());
    } catch (e) { setTrkErr(e.message); } finally { setBusy(false); }
  };

  const attachTrackingToScenario = () => {
    let detections;
    try { detections = validateDetections(detText); }
    catch (e) { setTrkErr(e.message); return; }
    if (!detections.length) { setTrkErr("Add at least one detection."); return; }
    if (!requireZone(setTrkErr)) return;
    attach("tracking_inputs",
           { zone_id: activeZone, detections, offset_seconds: Number(trkOffset) || 0 });
    setTrkErr(null);
    setTrkNote(`Attached ${detections.length} detection(s) on ${activeZone}. `
               + "ByteTrack runs on them as part of the scenario.");
  };

  const visionInputs = scenario.vision_inputs || [];
  const trackingInputs = scenario.tracking_inputs || [];
  const hydraulicReadings = scenario.hydraulic_readings || [];

  return (
    <div className="panel">
      <div className="panel-title">Raw Model Inputs</div>
      <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
        Feed raw features to the trained models. Nothing runs automatically —
        each submission is explicit. <b>Add to scenario</b> makes an input part of
        the run itself, so its real model output becomes canonical events in the
        main pipeline; <b>Test inference</b> is only a standalone check.
      </p>

      <label className="field">
        <span>attach to zone</span>
        {zoneIds.length === 0 ? (
          <div className="err-msg">
            No zones defined yet. Add a zone in the builder before attaching model inputs.
          </div>
        ) : (
          <select value={activeZone} onChange={(e) => setZone(e.target.value)}>
            {zoneIds.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
        )}
      </label>

      <div className="tabs">
        {["hydraulic", "vision", "tracking"].map((t) => (
          <span key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t}
          </span>
        ))}
      </div>

      {tab === "hydraulic" && (
        <div>
          <div className="faint mono" style={{ fontSize: 11, marginBottom: 8 }}>
            17 sensors · one cycle array each (comma or space separated). The
            service computes the trained statistical features itself.
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
            {HYD_SENSORS.map(([s, unit, label]) => {
              const n = parseCycle(cycles[s] || "").length;
              return (
                <label className="field" key={s} style={{ marginBottom: 4 }}>
                  <span>{s} — {label} [{unit}] {n > 0 && <em className="faint">({n} pts)</em>}</span>
                  <input value={cycles[s]} placeholder="e.g. 155.6, 155.8, 156.0"
                    onChange={(e) => setCycles({ ...cycles, [s]: e.target.value })} />
                </label>
              );
            })}
          </div>
          <label className="field" style={{ marginTop: 10 }}>
            <span>or paste JSON {"{ sensor_data: { PS1: [...], ... } }"}</span>
            <textarea rows={2} onChange={(e) => pasteHydraulicJson(e.target.value)} />
          </label>
          {hydErr && <div className="err-msg">{hydErr}</div>}
          <div className="btn-row" style={{ marginTop: 10 }}>
            <button className="btn" disabled={busy} onClick={submitHydraulic}>Test inference</button>
            <button className="btn primary" disabled={!activeZone} onClick={attachHydraulicToScenario}>
              Add to scenario
            </button>
          </div>
          <Attached
            label="hydraulic reading" items={hydraulicReadings}
            describe={(h) => `${h.zone_id} · ${Object.keys(h.sensor_data || {}).length} sensors `
                             + `· +${h.offset_seconds ?? 0}s`}
            onRemove={(i) => detach("hydraulic_readings", i)} />
          <Result data={hydRes} />
        </div>
      )}

      {tab === "vision" && (
        <div>
          <div className="faint mono" style={{ fontSize: 11, marginBottom: 8 }}>
            JPEG / PNG / WebP · max 8 MB. Video is not supported by this endpoint —
            extract a frame and upload it as an image.
          </div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <label className="field">
              <span>worker_id (optional)</span>
              <input value={visWorker} placeholder="W-003"
                     onChange={(e) => setVisWorker(e.target.value)} />
            </label>
            <label className="field">
              <span>offset_seconds</span>
              <input type="number" min={0} value={visOffset}
                     onChange={(e) => setVisOffset(e.target.value)} />
            </label>
          </div>
          <div className="btn-row">
            <button className="btn" onClick={() => fileRef.current?.click()}>Choose image</button>
            <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp"
              onChange={onImage} style={{ display: "none" }} />
            <button className="btn" disabled={busy || !imgB64} onClick={submitImage}>
              Test inference
            </button>
            <button className="btn primary" disabled={!imgB64 || !activeZone}
                    onClick={attachVisionToScenario}>
              Add to scenario
            </button>
          </div>
          {imgErr && <div className="err-msg" style={{ marginTop: 6 }}>{imgErr}</div>}
          {imgNote && <div className="audit-ok" style={{ marginTop: 6 }}>{imgNote}</div>}
          {preview && (
            <div style={{ marginTop: 10, position: "relative", display: "inline-block" }}>
              <img src={preview} alt="preview" style={{ maxWidth: 320, borderRadius: 8,
                   border: "1px solid var(--line)" }} />
              {visRes?.prediction?.detections?.map((d, i) => (
                <div key={i} style={{
                  position: "absolute", border: "2px solid var(--red)",
                  left: d.bbox?.[0], top: d.bbox?.[1],
                  width: d.bbox?.[2], height: d.bbox?.[3], pointerEvents: "none",
                }}>
                  <span className="mono" style={{ fontSize: 9, background: "var(--red)",
                        color: "#fff", padding: "0 3px" }}>
                    {d.class} {Number(d.confidence ?? 0).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          )}
          <Attached
            label="frame" items={visionInputs}
            describe={(v) => `${v.image_id} · ${v.zone_id}`
                             + (v.worker_id ? ` · ${v.worker_id}` : "")
                             + ` · +${v.offset_seconds ?? 0}s`}
            onRemove={(i) => detach("vision_inputs", i)} />
          <Result data={visRes} />
        </div>
      )}

      {tab === "tracking" && (
        <div>
          <div className="faint mono" style={{ fontSize: 11, marginBottom: 8 }}>
            Detection array: each item needs <b>frame_id</b>, <b>bbox</b> [x,y,w,h],
            <b> class</b> and <b>confidence</b> in [0,1].
          </div>
          <label className="field">
            <span>detections (JSON array)</span>
            <textarea rows={5} value={detText} onChange={(e) => setDetText(e.target.value)} />
          </label>
          <label className="field">
            <span>offset_seconds</span>
            <input type="number" min={0} value={trkOffset}
                   onChange={(e) => setTrkOffset(e.target.value)} />
          </label>
          {trkErr && <div className="err-msg">{trkErr}</div>}
          {trkNote && <div className="audit-ok" style={{ marginTop: 6 }}>{trkNote}</div>}
          <div className="btn-row" style={{ marginTop: 8 }}>
            <button className="btn" onClick={() => {
              try { validateDetections(detText); setTrkErr(null); setTrkNote("Detections are valid."); }
              catch (e) { setTrkErr(e.message); setTrkNote(null); }
            }}>Validate</button>
            <button className="btn" disabled={busy} onClick={submitTracking}>
              Test inference
            </button>
            <button className="btn primary" disabled={!activeZone} onClick={attachTrackingToScenario}>
              Add to scenario
            </button>
          </div>
          <Attached
            label="tracking input" items={trackingInputs}
            describe={(t) => `${t.zone_id} · ${(t.detections || []).length} detection(s) `
                             + `· +${t.offset_seconds ?? 0}s`}
            onRemove={(i) => detach("tracking_inputs", i)} />
          <Result data={trkRes} />
        </div>
      )}
    </div>
  );
}
