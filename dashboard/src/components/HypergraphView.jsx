import React, { useCallback, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  ReactFlowProvider,
} from "reactflow";
import "reactflow/dist/style.css";
import { Share2, Filter, Layers, Maximize2 } from "lucide-react";

// Column assignment gives a readable left→right causal flow:
// evidence/actors → zones → compound rules → interventions.
const COLUMN = {
  sensor: 0,
  worker: 0,
  asset: 0,
  permit: 1,
  zone: 2,
  hazard: 3,
  rule: 3,
  intervention: 4,
};
const COL_X = [40, 250, 470, 720, 980];

const STATUS_SWATCH = {
  normal: "#10b981",
  warning: "#f59e0b",
  critical: "#ef4444",
  mitigated: "#06b6d4",
};

const FILTER_TYPES = ["zone", "sensor", "worker", "permit", "asset", "rule", "intervention"];

function layout(nodes) {
  const byCol = {};
  return nodes.map((n) => {
    const col = COLUMN[n.type] ?? 2;
    byCol[col] = (byCol[col] ?? 0) + 1;
    const idx = byCol[col] - 1;
    return {
      id: n.id,
      position: { x: COL_X[col] ?? 470, y: 40 + idx * 80 },
      data: { ...n },
      type: "safety",
    };
  });
}

function SafetyNode({ data, selected }) {
  const borderColor =
    data.status === "critical"
      ? "#ef4444"
      : data.status === "warning"
      ? "#f59e0b"
      : data.status === "mitigated"
      ? "#06b6d4"
      : "#10b981";

  return (
    <div
      style={{
        padding: "8px 12px",
        borderRadius: 6,
        backgroundColor: "#ffffff",
        border: `2px solid ${borderColor}`,
        boxShadow: selected ? "0 0 0 2px #0d9488" : "0 1px 3px rgba(0,0,0,0.1)",
        minWidth: 120,
        fontSize: 12,
      }}
    >
      <div
        style={{
          fontSize: 9,
          fontWeight: 700,
          textTransform: "uppercase",
          color: "#64748b",
          fontFamily: "var(--font-mono)",
        }}
      >
        {data.type}
      </div>
      <div style={{ fontWeight: 600, color: "#0f172a", marginTop: 2 }}>{data.label || data.id}</div>
    </div>
  );
}

const nodeTypes = { safety: SafetyNode };

function edgeStyle(e) {
  if (e.cut) return { stroke: "#06b6d4", strokeWidth: 2.4, strokeDasharray: "5 3" };
  if (e.causal_path) return { stroke: "#ef4444", strokeWidth: 2.2 };
  return { stroke: "#cbd5e1", strokeWidth: 1.2 };
}

function InnerGraph({ graph, filters }) {
  const [selected, setSelected] = useState(null);
  const rf = useReactFlow();

  const visibleIds = useMemo(() => {
    const s = new Set();
    graph.nodes.forEach((n) => {
      if (filters.has(n.type)) s.add(n.id);
    });
    return s;
  }, [graph, filters]);

  const rfNodes = useMemo(
    () => layout(graph.nodes.filter((n) => visibleIds.has(n.id))),
    [graph, visibleIds]
  );

  const rfEdges = useMemo(
    () =>
      graph.edges
        .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
        .map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.relation,
          animated: !!e.cut || !!e.causal_path,
          style: edgeStyle(e),
          labelStyle: { fill: "#64748b", fontSize: 9, fontFamily: "monospace" },
          labelBgStyle: { fill: "#ffffff", fillOpacity: 0.9 },
          data: e,
        })),
    [graph, visibleIds]
  );

  const onNodeClick = useCallback((_, node) => setSelected({ kind: "node", ...node.data }), []);
  const onEdgeClick = useCallback((_, edge) => setSelected({ kind: "edge", ...edge.data }), []);

  return (
    <>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onPaneClick={() => setSelected(null)}
        fitView
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#cbd5e1" gap={20} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => STATUS_SWATCH[n.data?.status] ?? "#94a3b8"}
          maskColor="rgba(241,245,249,0.7)"
          style={{ background: "#ffffff", border: "1px solid #e2e8f0" }}
        />
      </ReactFlow>

      <div style={{ position: "absolute", bottom: 12, left: 12, zIndex: 6 }}>
        <button
          className="action-btn"
          style={{ padding: "4px 8px", fontSize: 11 }}
          onClick={() => rf.fitView({ duration: 400 })}
        >
          <Maximize2 size={12} />
          <span>Fit Screen</span>
        </button>
      </div>

      {selected && (
        <div
          style={{
            position: "absolute",
            top: 12,
            right: 12,
            zIndex: 10,
            width: 260,
            backgroundColor: "#ffffff",
            border: "1px solid #cbd5e1",
            borderRadius: 6,
            padding: 12,
            boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>
            {selected.kind === "node" ? "Node" : "Edge"} Inspector
          </div>
          {selected.kind === "node" ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11.5 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <b style={{ color: "#64748b" }}>ID:</b>
                <span className="mono" style={{ color: "#0f172a" }}>{selected.id}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <b style={{ color: "#64748b" }}>Type:</b>
                <span>{selected.type}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <b style={{ color: "#64748b" }}>Status:</b>
                <span style={{ fontWeight: 600, color: STATUS_SWATCH[selected.status] || "#0f172a" }}>
                  {selected.status}
                </span>
              </div>
              {selected.risk != null && (
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <b style={{ color: "#64748b" }}>Risk:</b>
                  <span className="mono">{selected.risk?.toFixed?.(2) ?? selected.risk}</span>
                </div>
              )}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11.5 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <b style={{ color: "#64748b" }}>Relation:</b>
                <span>{selected.relation}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <b style={{ color: "#64748b" }}>Source:</b>
                <span className="mono">{selected.source}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <b style={{ color: "#64748b" }}>Target:</b>
                <span className="mono">{selected.target}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}

export default function HypergraphView({ graph, loading, error }) {
  const [filters, setFilters] = useState(new Set(FILTER_TYPES));

  const toggle = (t) =>
    setFilters((prev) => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });

  return (
    <div className="panel-box" style={{ padding: 20, marginBottom: 20 }}>
      <div className="panel-header-row" style={{ marginBottom: 12 }}>
        <div>
          <span className="panel-title-text">INTERACTIVE SAFETY HYPERGRAPH</span>
          <span className="panel-meta-text" style={{ marginLeft: 12 }}>
            TOPOLOGY · PROPAGATION · CASUAL CUTS
          </span>
        </div>
      </div>

      <div className="filter-pills-row" style={{ marginBottom: 12 }}>
        {FILTER_TYPES.map((t) => (
          <button
            key={t}
            className={`filter-pill ${filters.has(t) ? "active" : ""}`}
            style={{ padding: "3px 10px", fontSize: 10.5 }}
            onClick={() => toggle(t)}
          >
            {t}
          </button>
        ))}
        <button
          className="action-btn"
          style={{ padding: "3px 8px", fontSize: 10.5, marginLeft: 6 }}
          onClick={() => setFilters(new Set(FILTER_TYPES))}
        >
          Reset
        </button>
      </div>

      <div
        style={{
          width: "100%",
          height: 380,
          backgroundColor: "#f8fafc",
          borderRadius: 6,
          border: "1px solid #e2e8f0",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {loading ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#64748b" }}>
            Building hypergraph from scenario…
          </div>
        ) : error ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#ef4444" }}>
            Graph error: {String(error)}
          </div>
        ) : !graph || graph.nodes.length === 0 ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#64748b" }}>
            No graph nodes generated.
          </div>
        ) : (
          <ReactFlowProvider>
            <InnerGraph graph={graph} filters={filters} />
          </ReactFlowProvider>
        )}
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 10, fontSize: 11, fontWeight: 600 }}>
        <span style={{ color: "#10b981" }}>● normal</span>
        <span style={{ color: "#f59e0b" }}>● warning</span>
        <span style={{ color: "#ef4444" }}>● critical</span>
        <span style={{ color: "#06b6d4" }}>● mitigated</span>
        <span style={{ color: "#ef4444" }}>— causal path</span>
        <span style={{ color: "#06b6d4" }}>- - - minimum cut</span>
      </div>
    </div>
  );
}
