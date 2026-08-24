import React, { useState, useMemo, useRef } from 'react';
import './FactoryMap.css';

const SVG_WIDTH = 1000;
const SVG_HEIGHT = 620;

const COLORS = {
  safe: 'rgba(16, 185, 129, 0.15)',
  warning: 'rgba(245, 158, 11, 0.2)',
  critical: 'rgba(239, 68, 68, 0.25)',
  safeBorder: '#10b981',
  warningBorder: '#f59e0b',
  criticalBorder: '#ef4444',
  text: '#ffffff',
  bg: '#0f111a',
};

// Zone fill tints that match the uploaded floor-plan image
// (green = standard/safe, yellow = high-risk, red = gas-hazard)
const HAZARD_TINT = {
  gas_hazard: 'rgba(239,68,68,0.18)',
  high_risk:  'rgba(234,179,8,0.18)',
  standard:   'rgba(16,185,129,0.10)',
  propagation:'rgba(234,179,8,0.12)',
};

const getRiskColor = (riskScore) => {
  if (riskScore == null) return { fill: 'rgba(255,255,255,0.04)', stroke: 'rgba(255,255,255,0.18)' };
  if (riskScore < 0.3) return { fill: COLORS.safe, stroke: COLORS.safeBorder };
  if (riskScore < 0.6) return { fill: COLORS.warning, stroke: COLORS.warningBorder };
  return { fill: COLORS.critical, stroke: COLORS.criticalBorder };
};

// ---------------------------------------------------------------------------
// Hardcoded floor-plan layout for the Steelforge factory.
// Zone IDs match the backend hypergraph: zone-1 … zone-6.
//
//   ┌─────────────────────────┬───────────────────────────┐
//   │   zone-1 (Coke Oven)    │  zone-2 (Blast Furnace)   │
//   │       gas_hazard         │       high_risk           │
//   ├─────────────────────────┼───────────────────────────┤
//   │ zone-4 (Shared Utils)   │  zone-3 (Machine Shop)    │
//   │     propagation          │   rotating_equipment      │
//   ├────────────┬────────────┴───────────────────────────┤
//   │ zone-5     │  zone-6 (Control Room)                 │
//   │ CCTV/PPE   │       admin                            │
//   └────────────┴────────────────────────────────────────┘
// ---------------------------------------------------------------------------
const STEELFORGE_LAYOUT = {
  'zone-1': { x_norm: 0.02, y_norm: 0.02, w_norm: 0.47, h_norm: 0.38, color: 'rgba(220,38,38,0.18)',  stroke: '#ef4444' },
  'zone-2': { x_norm: 0.51, y_norm: 0.02, w_norm: 0.47, h_norm: 0.38, color: 'rgba(202,138,4,0.22)',  stroke: '#eab308' },
  'zone-4': { x_norm: 0.02, y_norm: 0.44, w_norm: 0.47, h_norm: 0.28, color: 'rgba(202,138,4,0.12)',  stroke: '#a3870a' },
  'zone-3': { x_norm: 0.51, y_norm: 0.44, w_norm: 0.47, h_norm: 0.28, color: 'rgba(22,163,74,0.18)',  stroke: '#22c55e' },
  'zone-5': { x_norm: 0.02, y_norm: 0.76, w_norm: 0.25, h_norm: 0.22, color: 'rgba(16,185,129,0.14)', stroke: '#10b981' },
  'zone-6': { x_norm: 0.29, y_norm: 0.76, w_norm: 0.69, h_norm: 0.22, color: 'rgba(16,185,129,0.14)', stroke: '#10b981' },
};

// Corridor connector segments between zone rows
const CORRIDORS = [
  { x: 0.48, y: 0.14, w: 0.03, h: 0.12 },  // zone-1 ↔ zone-2 top
  { x: 0.48, y: 0.52, w: 0.03, h: 0.10 },  // zone-4 ↔ zone-3 mid
  { x: 0.25, y: 0.71, w: 0.04, h: 0.06 },  // zone-5 ↔ zone-6 bottom
];

function getLayout(zoneId) {
  return STEELFORGE_LAYOUT[zoneId] || null;
}

export default function FactoryMap({
  zones = [],
  sensors = [],
  workers = [],
  assets = [],
  permits = [],
  riskLevels = {},
  causalPaths = [],
  interventions = [],
  activatedRules = [],
  currentFloor = 0,
  floors = ['Ground'],
  onFloorChange,
  showCausalFocus = false,
  entities = [],
}) {
  const [hoverInfo, setHoverInfo] = useState(null);
  const containerRef = useRef(null);

  // -------------------------------------------------------------------------
  // Zone layout: prefer hardcoded Steelforge coords, fall back to auto-grid
  // -------------------------------------------------------------------------
  const layoutedZones = useMemo(() => {
    const out = [];
    const unpositioned = [];

    zones.forEach(z => {
      // Graph nodes from the backend carry `id` but no `zone_id`.
      // Scenario zones carry `zone_id`. Normalise once here so that all
      // downstream code (zoneMap, riskLevels lookup, entity placement,
      // zone rendering) consistently works via zone_id.
      const zoneId = z.zone_id ?? z.id;
      const normalised = { ...z, zone_id: zoneId };

      const preset = getLayout(zoneId);
      if (preset) {
        out.push({
          ...normalised,
          x: preset.x_norm * SVG_WIDTH,
          y: preset.y_norm * SVG_HEIGHT,
          w: preset.w_norm * SVG_WIDTH,
          h: preset.h_norm * SVG_HEIGHT,
          _presetColor:  preset.color,
          _presetStroke: preset.stroke,
        });
      } else if (z.x_norm != null && z.y_norm != null && z.w_norm != null && z.h_norm != null) {
        out.push({
          ...normalised,
          x: z.x_norm * SVG_WIDTH,
          y: z.y_norm * SVG_HEIGHT,
          w: z.w_norm * SVG_WIDTH,
          h: z.h_norm * SVG_HEIGHT,
        });
      } else {
        unpositioned.push(normalised);
      }
    });

    // Auto-grid for any zones not in the preset map
    if (unpositioned.length > 0) {
      const cols = Math.min(3, Math.ceil(Math.sqrt(unpositioned.length)));
      const pad = 20;
      const startX = 50;
      const startY = 50;
      const cellW = (SVG_WIDTH - startX * 2) / cols;
      const cellH = (SVG_HEIGHT - startY * 2) / Math.ceil(unpositioned.length / cols);
      unpositioned.forEach((z, i) => {
        const c = i % cols;
        const r = Math.floor(i / cols);
        out.push({
          ...z,
          x: startX + c * cellW + pad,
          y: startY + r * cellH + pad,
          w: cellW - pad * 2,
          h: cellH - pad * 2,
        });
      });
    }

    return out;
  }, [zones]);

  // Backward-compat: parse old `entities` prop
  const processedSensors = sensors.length ? sensors : entities.filter(e => e.type === 'sensor' || e.sensor_id);
  const processedWorkers = workers.length ? workers : entities.filter(e => e.type === 'worker' || e.worker_id);
  const processedAssets  = assets.length  ? assets  : entities.filter(e => e.type === 'asset'  || e.asset_id);

  const causalNodes = useMemo(() => {
    if (!showCausalFocus) return new Set();
    const nodes = new Set();
    causalPaths.forEach(p => { nodes.add(p.source); nodes.add(p.target); });
    return nodes;
  }, [causalPaths, showCausalFocus]);

  const zoneMap = useMemo(() => {
    const map = new Map();
    layoutedZones.forEach(z => map.set(z.zone_id, z));
    return map;
  }, [layoutedZones]);

  // Entity coordinate placement inside their zone
  const entityCoords = useMemo(() => {
    const coords = new Map();

    layoutedZones.forEach(z => {
      coords.set(z.zone_id, { x: z.x + z.w / 2, y: z.y + z.h / 2 });

      // Match by top-level zone/zone_id (scenario nodes) OR metadata.zone/zone_id (graph nodes)
      const inZone = (e) =>
        e.zone === z.zone_id || e.zone_id === z.zone_id ||
        e.metadata?.zone === z.zone_id || e.metadata?.zone_id === z.zone_id;
      const zSensors = processedSensors.filter(inZone);
      const zWorkers = processedWorkers.filter(inZone);
      const zAssets  = processedAssets.filter(inZone);
      const zPermits = permits.filter(inZone);

      let eIndex = 0;
      const eTotal = zSensors.length + zWorkers.length + zAssets.length + zPermits.length;

      const placeEntity = (id) => {
        const cols = Math.max(2, Math.ceil(Math.sqrt(Math.max(4, eTotal))));
        const col  = eIndex % cols;
        const row  = Math.floor(eIndex / cols);
        const cellW = (z.w - 50) / cols;
        const cellH = (z.h - 50) / (Math.ceil(eTotal / cols) || 1);
        const ex = z.x + 25 + col * cellW + cellW / 2;
        const ey = z.y + 38 + row * cellH + cellH / 2;
        coords.set(id, { x: ex, y: ey });
        eIndex++;
        return { x: ex, y: ey };
      };

      zSensors.forEach(s => s._pos = placeEntity(s.id || s.sensor_id));
      zWorkers.forEach(w => w._pos = placeEntity(w.id || w.worker_id));
      zAssets.forEach(a  => a._pos = placeEntity(a.id  || a.asset_id));
      zPermits.forEach(p => p._pos = placeEntity(p.id  || p.permit_id));
    });

    activatedRules.forEach(r => {
      const z = zoneMap.get(r.zone || r.zone_id);
      if (z) coords.set(r.id, { x: z.x + z.w - 20, y: z.y + 20 });
    });

    interventions.forEach(int => {
      const targetPos = coords.get(int.target || int.target_id);
      if (targetPos) coords.set(int.id, { x: targetPos.x, y: targetPos.y + 30 });
    });

    return coords;
  }, [layoutedZones, processedSensors, processedWorkers, processedAssets, permits,
      activatedRules, interventions, zoneMap]);

  const handleMouseMove = (e, info) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setHoverInfo({ ...info, x: e.clientX - rect.left, y: e.clientY - rect.top });
  };
  const handleMouseLeave = () => setHoverInfo(null);

  return (
    <div className="factory-map-container" ref={containerRef}>
      {/* Header */}
      <div className="factory-map-header">
        <h3 className="factory-map-title">Factory Floor Layout</h3>
        <div className="factory-map-controls">
          {floors && floors.length > 1 && (
            <select className="floor-select" value={currentFloor}
              onChange={e => onFloorChange && onFloorChange(e.target.value)}>
              {floors.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          )}
          {typeof showCausalFocus !== 'undefined' && (
            <button className={`map-control-btn ${showCausalFocus ? 'active' : ''}`}>
              Causal Focus {showCausalFocus ? 'ON' : 'OFF'}
            </button>
          )}
        </div>
      </div>

      <div className="factory-map-svg-wrapper">
        <svg viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`} className="factory-svg">
          <defs>
            {/* Glow filters */}
            <filter id="glow-red" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="4" result="blur"/>
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
            <filter id="glow-amber" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="3" result="blur"/>
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
            {/* Arrow markers for causal paths */}
            <marker id="arrow-critical" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444"/>
            </marker>
            <marker id="arrow-warning" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#f59e0b"/>
            </marker>
            <marker id="arrow-mitigated" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#06b6d4"/>
            </marker>
          </defs>

          {/* ---- Corridor connectors (subtle) ---- */}
          {CORRIDORS.map((c, i) => (
            <rect key={`corridor-${i}`}
              x={c.x * SVG_WIDTH} y={c.y * SVG_HEIGHT}
              width={c.w * SVG_WIDTH} height={c.h * SVG_HEIGHT}
              fill="rgba(100,116,139,0.15)" rx={2}/>
          ))}

          {/* ---- Zone adjacency lines (drawn before zones) ---- */}
          {/* Drawn as subtle connecting lines between adjacent zone centres */}

          {/* ---- Zones ---- */}
          {layoutedZones.map(zone => {
            const risk = riskLevels[zone.zone_id] ?? null;
            const riskStyle = getRiskColor(risk);

            // Use preset color when no risk score yet; blend with risk color once available
            const fillColor  = risk != null ? riskStyle.fill  : (zone._presetColor  || HAZARD_TINT[zone.hazard_class] || 'rgba(255,255,255,0.04)');
            const strokeColor= risk != null ? riskStyle.stroke: (zone._presetStroke || 'rgba(255,255,255,0.2)');
            const isCritical = risk != null && risk > 0.6;

            const isFocused = !showCausalFocus || causalNodes.has(zone.zone_id);
            const opacity = showCausalFocus && !isFocused ? 0.25 : 1;

            return (
              <g key={zone.zone_id}
                className={`zone-group ${isCritical ? 'zone-critical' : ''}`}
                style={{ opacity }}
                onMouseMove={e => handleMouseMove(e, { type: 'zone', data: { ...zone, risk } })}
                onMouseLeave={handleMouseLeave}>
                {/* Zone background */}
                <rect x={zone.x} y={zone.y} width={zone.w} height={zone.h} rx={10}
                  fill={fillColor} stroke={strokeColor} strokeWidth={isCritical ? 2.5 : 1.5}
                  className="zone-rect"
                  filter={isCritical ? 'url(#glow-red)' : undefined}/>
                {/* Hazard-class badge strip at top */}
                <rect x={zone.x + 8} y={zone.y + 8} width={zone.w - 16} height={24} rx={5}
                  fill="rgba(0,0,0,0.35)"/>
                {/* Zone name */}
                <text x={zone.x + zone.w / 2} y={zone.y + 24} className="zone-label"
                  textAnchor="middle" fontSize={13} fontWeight="600" fill="#fff">
                  {zone.name || zone.zone_id}
                </text>
              </g>
            );
          })}

          {/* ---- Causal paths ---- */}
          {causalPaths.map((path, i) => {
            const src = entityCoords.get(path.source);
            const tgt = entityCoords.get(path.target);
            if (!src || !tgt) return null;
            const isMitigated = path.cut || path.relation === 'mitigates';
            const mx = (src.x + tgt.x) / 2;
            const my = (src.y + tgt.y) / 2 - 40;
            return (
              <g key={`path-${i}`}>
                <path d={`M ${src.x} ${src.y} Q ${mx} ${my} ${tgt.x} ${tgt.y}`}
                  className={`causal-path ${isMitigated ? 'mitigated' : 'critical'}`}
                  markerEnd={isMitigated ? 'url(#arrow-mitigated)' : 'url(#arrow-critical)'}/>
                {isMitigated && (
                  <text x={mx} y={my} fontSize={14} fill="#06b6d4"
                    textAnchor="middle" dominantBaseline="middle">✂️</text>
                )}
              </g>
            );
          })}

          {/* ---- Sensors ---- */}
          {processedSensors.map(s => {
            if (!s._pos) return null;
            if (showCausalFocus && !causalNodes.has(s.id || s.sensor_id)) return null;
            return (
              <g key={s.id || s.sensor_id}
                transform={`translate(${s._pos.x}, ${s._pos.y})`}
                className="entity-icon"
                onMouseMove={e => handleMouseMove(e, { type: 'sensor', data: s })}
                onMouseLeave={handleMouseLeave}>
                <circle r={14} fill="#0f172a" stroke="#3b82f6" strokeWidth={1.8}/>
                {/* Sensor crosshair icon */}
                <circle r={4} fill="none" stroke="#60a5fa" strokeWidth={1.2}/>
                <line x1={0} y1={-8} x2={0} y2={-4} stroke="#60a5fa" strokeWidth={1.2}/>
                <line x1={0} y1={4} x2={0} y2={8} stroke="#60a5fa" strokeWidth={1.2}/>
                <line x1={-8} y1={0} x2={-4} y2={0} stroke="#60a5fa" strokeWidth={1.2}/>
                <line x1={4} y1={0} x2={8} y2={0} stroke="#60a5fa" strokeWidth={1.2}/>
                <text x={0} y={24} className="entity-text" textAnchor="middle" fontSize={9}>
                  {(s.id || s.sensor_id || '').replace('GS-','').replace('VENT-','')}
                </text>
              </g>
            );
          })}

          {/* ---- Workers ---- */}
          {processedWorkers.map(w => {
            if (!w._pos) return null;
            if (showCausalFocus && !causalNodes.has(w.id || w.worker_id)) return null;
            const hasPPE = w.metadata?.ppe_compliant ?? w.ppe_compliant ?? (!(w.missing_ppe?.length));
            return (
              <g key={w.id || w.worker_id}
                transform={`translate(${w._pos.x}, ${w._pos.y})`}
                className="entity-icon"
                onMouseMove={e => handleMouseMove(e, { type: 'worker', data: w })}
                onMouseLeave={handleMouseLeave}>
                <circle r={14} fill="#0f172a" stroke="#8b5cf6" strokeWidth={1.8}/>
                {/* Person silhouette */}
                <circle cx={0} cy={-4} r={3.5} fill="#c4b5fd"/>
                <path d="M -6 8 Q -6 1 0 1 Q 6 1 6 8" fill="#c4b5fd"/>
                {/* PPE status dot */}
                <circle cx={10} cy={-9} r={4.5}
                  fill={hasPPE ? '#10b981' : '#ef4444'}
                  stroke="#0f172a" strokeWidth={1.2}/>
                <text x={0} y={24} className="entity-text" textAnchor="middle" fontSize={9}>
                  {(w.id || w.worker_id || '').split('-').slice(-1)[0]}
                </text>
              </g>
            );
          })}

          {/* ---- Assets ---- */}
          {processedAssets.map(a => {
            if (!a._pos) return null;
            if (showCausalFocus && !causalNodes.has(a.id || a.asset_id)) return null;
            const isFailing = (a.failure_probability || a.metadata?.failure_prob || 0) > 0.5;
            const gearColor = isFailing ? '#fca5a5' : '#f9a8d4';
            return (
              <g key={a.id || a.asset_id}
                transform={`translate(${a._pos.x}, ${a._pos.y})`}
                className="entity-icon"
                onMouseMove={e => handleMouseMove(e, { type: 'asset', data: a })}
                onMouseLeave={handleMouseLeave}>
                <rect x={-14} y={-14} width={28} height={28} rx={5}
                  fill="#0f172a" stroke={isFailing ? '#ef4444' : '#ec4899'} strokeWidth={1.8}/>
                {/* Gear icon */}
                <circle r={4} fill="none" stroke={gearColor} strokeWidth={1.5}/>
                <line x1={0} y1={-8} x2={0} y2={8} stroke={gearColor} strokeWidth={1.2}/>
                <line x1={-8} y1={0} x2={8} y2={0} stroke={gearColor} strokeWidth={1.2}/>
                <line x1={-5.5} y1={-5.5} x2={5.5} y2={5.5} stroke={gearColor} strokeWidth={1.2}/>
                <line x1={5.5} y1={-5.5} x2={-5.5} y2={5.5} stroke={gearColor} strokeWidth={1.2}/>
                <text x={0} y={24} className="entity-text" textAnchor="middle" fontSize={9}>
                  {(a.id || a.asset_id || '').split('-')[0]}
                </text>
              </g>
            );
          })}

          {/* ---- Permits ---- */}
          {permits.map(p => {
            if (!p._pos) return null;
            if (showCausalFocus && !causalNodes.has(p.id || p.permit_id)) return null;
            return (
              <g key={p.id || p.permit_id}
                transform={`translate(${p._pos.x}, ${p._pos.y})`}
                className="entity-icon"
                onMouseMove={e => handleMouseMove(e, { type: 'permit', data: p })}
                onMouseLeave={handleMouseLeave}>
                <rect x={-13} y={-15} width={26} height={30} rx={3}
                  fill="#0f172a" stroke="#eab308" strokeWidth={1.8}/>
                {/* Document lines */}
                <line x1={-6} y1={-7} x2={6} y2={-7} stroke="#fde047" strokeWidth={1.2} strokeLinecap="round"/>
                <line x1={-6} y1={-2} x2={6} y2={-2} stroke="#fde047" strokeWidth={1.2} strokeLinecap="round"/>
                <line x1={-6} y1={3} x2={3} y2={3} stroke="#fde047" strokeWidth={1.2} strokeLinecap="round"/>
                <text x={0} y={25} className="entity-text" textAnchor="middle" fontSize={9}>PTW</text>
              </g>
            );
          })}

          {/* ---- Activated rules (warning triangles) ---- */}
          {activatedRules.map(r => {
            const pos = entityCoords.get(r.id);
            if (!pos) return null;
            return (
              <g key={r.id} transform={`translate(${pos.x}, ${pos.y})`}
                className="entity-icon"
                onMouseMove={e => handleMouseMove(e, { type: 'rule', data: r })}
                onMouseLeave={handleMouseLeave}>
                <path d="M 0 -13 L 15 12 L -15 12 z" fill="#ef4444" stroke="#7f1d1d" strokeWidth={1}/>
                <text x={0} y={8} fontSize={11} textAnchor="middle" fill="#fff" fontWeight="bold">!</text>
              </g>
            );
          })}

          {/* ---- Interventions ---- */}
          {interventions.map(int => {
            const pos = entityCoords.get(int.id);
            if (!pos) return null;
            return (
              <g key={int.id} transform={`translate(${pos.x}, ${pos.y})`}
                className="entity-icon"
                onMouseMove={e => handleMouseMove(e, { type: 'intervention', data: int })}
                onMouseLeave={handleMouseLeave}>
                <rect x={-20} y={-10} width={40} height={20} rx={10}
                  fill="#ef4444" stroke="#fff" strokeWidth={1}/>
                <text x={0} y={4} fontSize={10} textAnchor="middle" fill="#fff">🛑</text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="map-legend">
        <div className="legend-item">
          <div className="legend-color" style={{ background: COLORS.safeBorder }}/>
          <span>Safe (&lt;0.3)</span>
        </div>
        <div className="legend-item">
          <div className="legend-color" style={{ background: COLORS.warningBorder }}/>
          <span>Warning (0.3-0.6)</span>
        </div>
        <div className="legend-item">
          <div className="legend-color" style={{ background: COLORS.criticalBorder }}/>
          <span>Critical (&gt;0.6)</span>
        </div>
        <div className="legend-item"><div className="legend-color" style={{ background: '#3b82f6', borderRadius: '50%' }}/><span>Sensor</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: '#8b5cf6', borderRadius: '50%' }}/><span>Worker</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: '#ec4899' }}/><span>Asset</span></div>
        <div className="legend-item"><div className="legend-color" style={{ background: '#eab308' }}/><span>Permit</span></div>
      </div>

      {/* Tooltip */}
      {hoverInfo && (
        <div className="map-tooltip" style={{ left: hoverInfo.x, top: hoverInfo.y }}>
          {hoverInfo.type === 'zone' && (
            <>
              <h4>{hoverInfo.data.name || hoverInfo.data.zone_id}</h4>
              <p><span className="label">Risk Score:</span>
                 <span className="value">{hoverInfo.data.risk != null ? hoverInfo.data.risk.toFixed(2) : '—'}</span></p>
              {hoverInfo.data.hazard_class &&
                <p><span className="label">Hazard:</span>
                   <span className="value" style={{textTransform:'capitalize'}}>{hoverInfo.data.hazard_class}</span></p>}
              {hoverInfo.data.ventilation_status &&
                <p><span className="label">Ventilation:</span>
                   <span className="value">{hoverInfo.data.ventilation_status}</span></p>}
            </>
          )}
          {hoverInfo.type === 'sensor' && (
            <>
              <h4>{hoverInfo.data.label || hoverInfo.data.sensor_id || hoverInfo.data.id}</h4>
              {hoverInfo.data.metadata?.value !== undefined &&
                <p><span className="label">Reading:</span>
                   <span className="value">{hoverInfo.data.metadata.value} {hoverInfo.data.metadata.unit}</span></p>}
              {hoverInfo.data.status &&
                <p><span className="label">Status:</span>
                   <span className="value">{hoverInfo.data.status}</span></p>}
            </>
          )}
          {hoverInfo.type === 'worker' && (
            <>
              <h4>{hoverInfo.data.label || hoverInfo.data.worker_id || hoverInfo.data.id}</h4>
              <p><span className="label">PPE:</span>
                 <span className="value">
                   {(hoverInfo.data.metadata?.ppe_compliant ?? hoverInfo.data.ppe_compliant ?? !(hoverInfo.data.missing_ppe?.length))
                     ? '✅ Compliant' : '❌ Missing'}
                 </span></p>
              {hoverInfo.data.missing_ppe?.length > 0 &&
                <p><span className="label">Missing:</span>
                   <span className="value">{hoverInfo.data.missing_ppe.join(', ')}</span></p>}
            </>
          )}
          {hoverInfo.type === 'asset' && (
            <>
              <h4>{hoverInfo.data.label || hoverInfo.data.asset_id || hoverInfo.data.id}</h4>
              {hoverInfo.data.failure_probability != null &&
                <p><span className="label">Fail Prob:</span>
                   <span className="value">{(hoverInfo.data.failure_probability * 100).toFixed(1)}%</span></p>}
              {hoverInfo.data.condition &&
                <p><span className="label">Condition:</span>
                   <span className="value">{hoverInfo.data.condition}</span></p>}
            </>
          )}
          {hoverInfo.type === 'permit' && (
            <>
              <h4>{hoverInfo.data.label || hoverInfo.data.permit_id || hoverInfo.data.id}</h4>
              {hoverInfo.data.status &&
                <p><span className="label">Status:</span>
                   <span className="value">{hoverInfo.data.status}</span></p>}
              {hoverInfo.data.permit_type &&
                <p><span className="label">Type:</span>
                   <span className="value">{hoverInfo.data.permit_type}</span></p>}
            </>
          )}
          {hoverInfo.type === 'rule' && (
            <>
              <h4>Rule Triggered</h4>
              <p><span className="value">{hoverInfo.data.label || hoverInfo.data.id}</span></p>
            </>
          )}
          {hoverInfo.type === 'intervention' && (
            <>
              <h4>Recommended Action</h4>
              <p><span className="value">{hoverInfo.data.label || hoverInfo.data.id}</span></p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
