import React, { useRef, useState, useCallback, useEffect } from "react";
import "./BlueprintCanvas.css";

const HAZARD_COLORS = {
  flammable:      { bg: "rgba(249,115,22,0.18)",  border: "#f97316", label: "#fed7aa" },
  toxic:          { bg: "rgba(168,85,247,0.18)",   border: "#a855f7", label: "#e9d5ff" },
  confined_space: { bg: "rgba(234,179,8,0.18)",    border: "#eab308", label: "#fef08a" },
  electrical:     { bg: "rgba(59,130,246,0.18)",   border: "#3b82f6", label: "#bfdbfe" },
  general:        { bg: "rgba(148,163,184,0.1)",   border: "#64748b", label: "#cbd5e1" },
  standard:       { bg: "rgba(148,163,184,0.1)",   border: "#64748b", label: "#cbd5e1" },
};

const SENSOR_ICONS = {
  gas:         "⛽",
  temperature: "🌡",
  pressure:    "🔵",
  vibration:   "〰",
  smoke:       "💨",
  flame:       "🔥",
};

const HAZARD_CLASSES = Object.keys(HAZARD_COLORS);
const TOOLS = ["select", "draw", "sensor", "link"];

let _zoneCounter = 100;
let _sensorCounter = 100;

function nextZoneId()   { return `zone-${++_zoneCounter}`; }
function nextSensorId() { return `sensor-${++_sensorCounter}`; }

// Normalize zones from backend (has x_norm etc.) into canvas zones (has x,y,w,h in px relative to image)
function normalizeZones(rawZones, imgW, imgH) {
  return rawZones.map((z) => ({
    ...z,
    // If already has pixel coords keep them; else convert from norm
    x: z.x ?? (z.x_norm ?? 0.05) * imgW,
    y: z.y ?? (z.y_norm ?? 0.05) * imgH,
    w: z.w ?? (z.w_norm ?? 0.2) * imgW,
    h: z.h ?? (z.h_norm ?? 0.2) * imgH,
  }));
}

function normalizeSensors(rawSensors, imgW, imgH) {
  return rawSensors.map((s) => ({
    ...s,
    x: s.x ?? (s.x_norm ?? 0.1) * imgW,
    y: s.y ?? (s.y_norm ?? 0.1) * imgH,
  }));
}

export default function BlueprintCanvas({
  imageDataUrl,
  initialZones = [],
  initialAdjacency = [],
  initialSensors = [],
  onConfirm,
  confirming = false,
}) {
  const canvasRef = useRef(null);       // the overlay SVG container
  const imgRef   = useRef(null);
  const [imgSize, setImgSize] = useState({ w: 800, h: 600 });
  const [initialized, setInitialized] = useState(false);

  const [zones,     setZones]     = useState([]);
  const [sensors,   setSensors]   = useState([]);
  const [adjacency, setAdjacency] = useState([]);

  const [tool, setTool]   = useState("select");
  const [drawing, setDrawing]   = useState(null);   // { x0, y0, x1, y1 }
  const [selected, setSelected] = useState(null);   // { type: 'zone'|'sensor', id }
  const [linkStart, setLinkStart] = useState(null); // zone_id for link tool

  // Zone editor popup
  const [editZone, setEditZone] = useState(null);   // zone object being edited

  // Initialize zones/sensors once image loads and we know its size
  const onImgLoad = useCallback(() => {
    if (initialized) return;
    const el = imgRef.current;
    if (!el) return;
    const w = el.clientWidth  || 800;
    const h = el.clientHeight || 600;
    setImgSize({ w, h });
    setZones(normalizeZones(initialZones, w, h));
    setSensors(normalizeSensors(initialSensors, w, h));
    setAdjacency(initialAdjacency.map((a) => ({ ...a })));
    setInitialized(true);
  }, [initialized, initialZones, initialSensors, initialAdjacency]);

  // Re-init when initial data changes (e.g. after analysis completes)
  useEffect(() => {
    setInitialized(false);
  }, [initialZones, initialSensors, initialAdjacency]);

  // ------------------------------------------------------------------ //
  // Event → canvas coords
  // ------------------------------------------------------------------ //
  const toLocal = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  // ------------------------------------------------------------------ //
  // Mouse handlers
  // ------------------------------------------------------------------ //
  const onMouseDown = (e) => {
    if (e.button !== 0) return;
    const { x, y } = toLocal(e);

    if (tool === "draw") {
      setDrawing({ x0: x, y0: y, x1: x, y1: y });
      setSelected(null);
      return;
    }

    if (tool === "sensor") {
      const newSensor = {
        sensor_id: nextSensorId(),
        zone_id: closestZone(x, y)?.zone_id ?? (zones[0]?.zone_id || "zone-1"),
        modality: "gas",
        unit: "ppm",
        x, y,
      };
      setSensors((p) => [...p, newSensor]);
      return;
    }
  };

  const onMouseMove = (e) => {
    if (tool === "draw" && drawing) {
      const { x, y } = toLocal(e);
      setDrawing((d) => ({ ...d, x1: x, y1: y }));
    }
  };

  const onMouseUp = (e) => {
    if (tool === "draw" && drawing) {
      const x = Math.min(drawing.x0, drawing.x1);
      const y = Math.min(drawing.y0, drawing.y1);
      const w = Math.abs(drawing.x1 - drawing.x0);
      const h = Math.abs(drawing.y1 - drawing.y0);
      if (w > 20 && h > 20) {
        const newZone = {
          zone_id: nextZoneId(),
          name: `Zone ${zones.length + 1}`,
          hazard_class: "general",
          baseline_gas_threshold_ppm: 200,
          ventilation_status: "nominal",
          ventilation_flow_ratio: 1.0,
          x, y, w, h,
        };
        setZones((p) => [...p, newZone]);
        setEditZone(newZone);
      }
      setDrawing(null);
    }
  };

  // ------------------------------------------------------------------ //
  // Zone click (select/link)
  // ------------------------------------------------------------------ //
  const onZoneClick = (e, zone) => {
    e.stopPropagation();

    if (tool === "link") {
      if (!linkStart) {
        setLinkStart(zone.zone_id);
      } else if (linkStart !== zone.zone_id) {
        const exists = adjacency.some(
          (a) =>
            (a.zone_a === linkStart && a.zone_b === zone.zone_id) ||
            (a.zone_b === linkStart && a.zone_a === zone.zone_id)
        );
        if (!exists) {
          setAdjacency((p) => [...p, { zone_a: linkStart, zone_b: zone.zone_id, medium: "doorway" }]);
        }
        setLinkStart(null);
      }
      return;
    }

    if (tool === "select") {
      setSelected({ type: "zone", id: zone.zone_id });
      setEditZone({ ...zone });
    }
  };

  const onSvgClick = () => {
    if (tool !== "link") {
      setSelected(null);
      setLinkStart(null);
    }
  };

  // ------------------------------------------------------------------ //
  // Zone editor save
  // ------------------------------------------------------------------ //
  const saveZoneEdit = () => {
    setZones((prev) =>
      prev.map((z) => (z.zone_id === editZone.zone_id ? { ...z, ...editZone } : z))
    );
    setEditZone(null);
  };

  const deleteZone = (zone_id) => {
    setZones((p) => p.filter((z) => z.zone_id !== zone_id));
    setSensors((p) => p.filter((s) => s.zone_id !== zone_id));
    setAdjacency((p) => p.filter((a) => a.zone_a !== zone_id && a.zone_b !== zone_id));
    setEditZone(null);
    setSelected(null);
  };

  const deleteSensor = (sensor_id) => {
    setSensors((p) => p.filter((s) => s.sensor_id !== sensor_id));
    setSelected(null);
  };

  const deleteAdjacency = (idx) => {
    setAdjacency((p) => p.filter((_, i) => i !== idx));
  };

  // ------------------------------------------------------------------ //
  // Closest zone by center distance
  // ------------------------------------------------------------------ //
  const closestZone = (x, y) => {
    let best = null, bestDist = Infinity;
    for (const z of zones) {
      const cx = z.x + z.w / 2;
      const cy = z.y + z.h / 2;
      const d = Math.hypot(x - cx, y - cy);
      if (d < bestDist) { best = z; bestDist = d; }
    }
    return best;
  };

  // ------------------------------------------------------------------ //
  // Zone center helper for adjacency lines
  // ------------------------------------------------------------------ //
  const zoneCenter = (zone_id) => {
    const z = zones.find((z) => z.zone_id === zone_id);
    if (!z) return null;
    return { x: z.x + z.w / 2, y: z.y + z.h / 2 };
  };

  // ------------------------------------------------------------------ //
  // Confirm: convert pixel coords back to normalized + emit
  // ------------------------------------------------------------------ //
  const handleConfirm = () => {
    const { w: imgW, h: imgH } = imgSize;
    const outZones = zones.map(({ x, y, w, h, ...rest }) => ({
      ...rest,
      x_norm: x / imgW,
      y_norm: y / imgH,
      w_norm: w / imgW,
      h_norm: h / imgH,
    }));
    const outSensors = sensors.map(({ x, y, ...rest }) => ({
      ...rest,
      x_norm: x / imgW,
      y_norm: y / imgH,
    }));
    onConfirm?.({
      zones: outZones,
      zone_adjacency: adjacency,
      sensors: outSensors,
    });
  };

  // ------------------------------------------------------------------ //
  // Render
  // ------------------------------------------------------------------ //
  const { w: svgW, h: svgH } = imgSize;

  return (
    <div className="bc-root">
      {/* Toolbar */}
      <div className="bc-toolbar">
        <div className="bc-tool-group">
          {[
            { id: "select", icon: "↖", label: "Select & Edit" },
            { id: "draw",   icon: "⬜", label: "Draw Zone" },
            { id: "sensor", icon: "📍", label: "Place Sensor" },
            { id: "link",   icon: "🔗", label: "Link Zones" },
          ].map((t) => (
            <button
              key={t.id}
              id={`bc-tool-${t.id}`}
              className={`bc-tool-btn ${tool === t.id ? "bc-tool-btn-active" : ""}`}
              onClick={() => { setTool(t.id); setLinkStart(null); setSelected(null); }}
              title={t.label}
            >
              <span className="bc-tool-icon">{t.icon}</span>
              <span className="bc-tool-label">{t.label}</span>
            </button>
          ))}
        </div>

        <div className="bc-toolbar-info">
          {tool === "draw"   && "Click and drag to draw a zone rectangle"}
          {tool === "sensor" && "Click anywhere on the blueprint to place a sensor"}
          {tool === "link"   && (linkStart ? `Click second zone to link with "${linkStart}"` : "Click first zone to start a link")}
          {tool === "select" && "Click a zone or sensor to edit it"}
        </div>

        <button
          id="bc-confirm-btn"
          className="bc-confirm-btn"
          onClick={handleConfirm}
          disabled={zones.length === 0 || confirming}
        >
          {confirming ? <span className="bc-spinner" /> : "✓ Confirm & Launch"}
        </button>
      </div>

      <div className="bc-workspace">
        {/* Canvas area */}
        <div className="bc-canvas-wrap">
          <div
            className="bc-canvas"
            style={{ cursor: tool === "draw" ? "crosshair" : tool === "sensor" ? "cell" : "default" }}
          >
            {/* Blueprint image */}
            {imageDataUrl && (
              <img
                ref={imgRef}
                src={imageDataUrl}
                alt="Factory blueprint"
                className="bc-blueprint-img"
                onLoad={onImgLoad}
                draggable={false}
              />
            )}

            {/* SVG overlay */}
            <svg
              ref={canvasRef}
              className="bc-svg-overlay"
              width={svgW}
              height={svgH}
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onClick={onSvgClick}
            >
              {/* Adjacency lines */}
              {adjacency.map((a, i) => {
                const ca = zoneCenter(a.zone_a);
                const cb = zoneCenter(a.zone_b);
                if (!ca || !cb) return null;
                return (
                  <g key={i} onClick={(e) => { e.stopPropagation(); deleteAdjacency(i); }}>
                    <line
                      x1={ca.x} y1={ca.y} x2={cb.x} y2={cb.y}
                      stroke="#06b6d4"
                      strokeWidth="2"
                      strokeDasharray="6 4"
                      opacity="0.7"
                      style={{ cursor: "pointer" }}
                    />
                    <circle cx={(ca.x + cb.x) / 2} cy={(ca.y + cb.y) / 2} r="5" fill="#06b6d4" opacity="0.8" />
                  </g>
                );
              })}

              {/* Zones */}
              {zones.map((z) => {
                const colors = HAZARD_COLORS[z.hazard_class] || HAZARD_COLORS.general;
                const isSel = selected?.type === "zone" && selected.id === z.zone_id;
                const isLink = linkStart === z.zone_id;
                return (
                  <g key={z.zone_id} onClick={(e) => onZoneClick(e, z)} style={{ cursor: "pointer" }}>
                    <rect
                      x={z.x} y={z.y} width={z.w} height={z.h}
                      fill={colors.bg}
                      stroke={isSel ? "#fff" : isLink ? "#06b6d4" : colors.border}
                      strokeWidth={isSel || isLink ? 2.5 : 1.5}
                      strokeDasharray={tool === "link" ? "4 3" : "none"}
                      rx={4}
                    />
                    <text
                      x={z.x + z.w / 2}
                      y={z.y + 18}
                      textAnchor="middle"
                      fill={colors.label}
                      fontSize="11"
                      fontWeight="600"
                      style={{ pointerEvents: "none", userSelect: "none" }}
                    >
                      {z.name}
                    </text>
                    <text
                      x={z.x + z.w / 2}
                      y={z.y + 30}
                      textAnchor="middle"
                      fill={colors.border}
                      fontSize="9"
                      opacity="0.8"
                      style={{ pointerEvents: "none", userSelect: "none" }}
                    >
                      {z.hazard_class}
                    </text>
                  </g>
                );
              })}

              {/* Sensors */}
              {sensors.map((s) => {
                const isSel = selected?.type === "sensor" && selected.id === s.sensor_id;
                return (
                  <g
                    key={s.sensor_id}
                    onClick={(e) => { e.stopPropagation(); setSelected({ type: "sensor", id: s.sensor_id }); }}
                    style={{ cursor: "pointer" }}
                  >
                    <circle
                      cx={s.x} cy={s.y} r={isSel ? 13 : 10}
                      fill="rgba(15,23,38,0.85)"
                      stroke={isSel ? "#fff" : "#f97316"}
                      strokeWidth={isSel ? 2.5 : 1.5}
                    />
                    <text x={s.x} y={s.y + 4} textAnchor="middle" fontSize="10" style={{ pointerEvents: "none" }}>
                      {SENSOR_ICONS[s.modality] ?? "📡"}
                    </text>
                  </g>
                );
              })}

              {/* Drawing preview rect */}
              {drawing && (
                <rect
                  x={Math.min(drawing.x0, drawing.x1)}
                  y={Math.min(drawing.y0, drawing.y1)}
                  width={Math.abs(drawing.x1 - drawing.x0)}
                  height={Math.abs(drawing.y1 - drawing.y0)}
                  fill="rgba(249,115,22,0.08)"
                  stroke="#f97316"
                  strokeWidth="2"
                  strokeDasharray="5 3"
                  rx={4}
                  style={{ pointerEvents: "none" }}
                />
              )}
            </svg>
          </div>
        </div>

        {/* Right sidebar: zone list + editor */}
        <div className="bc-sidebar">
          <div className="bc-sidebar-section">
            <h3 className="bc-sidebar-title">
              Zones <span className="bc-badge">{zones.length}</span>
            </h3>
            <div className="bc-zone-list">
              {zones.map((z) => {
                const colors = HAZARD_COLORS[z.hazard_class] || HAZARD_COLORS.general;
                const isSel = selected?.type === "zone" && selected.id === z.zone_id;
                return (
                  <div
                    key={z.zone_id}
                    className={`bc-zone-item ${isSel ? "bc-zone-item-sel" : ""}`}
                    onClick={() => { setSelected({ type: "zone", id: z.zone_id }); setEditZone({ ...z }); setTool("select"); }}
                  >
                    <span className="bc-zone-dot" style={{ background: colors.border }} />
                    <div className="bc-zone-info">
                      <span className="bc-zone-name">{z.name}</span>
                      <span className="bc-zone-class">{z.hazard_class}</span>
                    </div>
                    <button
                      className="bc-del-btn"
                      onClick={(e) => { e.stopPropagation(); deleteZone(z.zone_id); }}
                      title="Delete zone"
                    >×</button>
                  </div>
                );
              })}
              {zones.length === 0 && (
                <p className="bc-empty">Use the Draw tool to create zones.</p>
              )}
            </div>
          </div>

          <div className="bc-sidebar-section">
            <h3 className="bc-sidebar-title">
              Sensors <span className="bc-badge">{sensors.length}</span>
            </h3>
            <div className="bc-zone-list">
              {sensors.map((s) => (
                <div
                  key={s.sensor_id}
                  className={`bc-zone-item ${selected?.type === "sensor" && selected.id === s.sensor_id ? "bc-zone-item-sel" : ""}`}
                >
                  <span style={{ fontSize: "14px" }}>{SENSOR_ICONS[s.modality] ?? "📡"}</span>
                  <div className="bc-zone-info">
                    <span className="bc-zone-name">{s.modality}</span>
                    <span className="bc-zone-class">{s.zone_id} · {s.unit}</span>
                  </div>
                  <button className="bc-del-btn" onClick={() => deleteSensor(s.sensor_id)} title="Delete sensor">×</button>
                </div>
              ))}
              {sensors.length === 0 && <p className="bc-empty">Use the Sensor tool to place sensors.</p>}
            </div>
          </div>

          <div className="bc-sidebar-section">
            <h3 className="bc-sidebar-title">
              Links <span className="bc-badge">{adjacency.length}</span>
            </h3>
            <div className="bc-zone-list">
              {adjacency.map((a, i) => (
                <div key={i} className="bc-zone-item">
                  <span style={{ fontSize: "11px", color: "#06b6d4" }}>⟷</span>
                  <div className="bc-zone-info">
                    <span className="bc-zone-name">{a.zone_a} ↔ {a.zone_b}</span>
                    <span className="bc-zone-class">{a.medium}</span>
                  </div>
                  <button className="bc-del-btn" onClick={() => deleteAdjacency(i)}>×</button>
                </div>
              ))}
              {adjacency.length === 0 && <p className="bc-empty">Use the Link tool to connect zones.</p>}
            </div>
          </div>
        </div>
      </div>

      {/* Zone editor popup */}
      {editZone && (
        <div className="bc-editor-overlay" onClick={() => setEditZone(null)}>
          <div className="bc-editor" onClick={(e) => e.stopPropagation()}>
            <h4 className="bc-editor-title">Edit Zone</h4>

            <label className="bc-ed-label">Name</label>
            <input
              className="bc-ed-input"
              value={editZone.name}
              onChange={(e) => setEditZone((z) => ({ ...z, name: e.target.value }))}
              autoFocus
            />

            <label className="bc-ed-label">Hazard Class</label>
            <div className="bc-ed-chips">
              {HAZARD_CLASSES.map((hc) => (
                <button
                  key={hc}
                  className={`bc-ed-chip ${editZone.hazard_class === hc ? "bc-ed-chip-sel" : ""}`}
                  style={editZone.hazard_class === hc ? { borderColor: HAZARD_COLORS[hc].border, color: HAZARD_COLORS[hc].label } : {}}
                  onClick={() => setEditZone((z) => ({ ...z, hazard_class: hc }))}
                >
                  {hc}
                </button>
              ))}
            </div>

            <label className="bc-ed-label">Gas Threshold (ppm)</label>
            <input
              type="number"
              className="bc-ed-input"
              value={editZone.baseline_gas_threshold_ppm}
              onChange={(e) => setEditZone((z) => ({ ...z, baseline_gas_threshold_ppm: parseFloat(e.target.value) || 200 }))}
            />

            <label className="bc-ed-label">Ventilation</label>
            <select
              className="bc-ed-input"
              value={editZone.ventilation_status}
              onChange={(e) => setEditZone((z) => ({ ...z, ventilation_status: e.target.value }))}
            >
              {["nominal", "degraded", "failed"].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>

            <div className="bc-ed-actions">
              <button className="bc-ed-save" onClick={saveZoneEdit}>Save</button>
              <button className="bc-ed-delete" onClick={() => deleteZone(editZone.zone_id)}>Delete Zone</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
