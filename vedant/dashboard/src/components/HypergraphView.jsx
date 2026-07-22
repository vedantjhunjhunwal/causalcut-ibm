import { useCallback, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  ReactFlowProvider,
} from "reactflow";
import "reactflow/dist/style.css";

// Column assignment gives a readable left→right causal flow:
// evidence/actors → zones → compound rules → interventions.
const COLUMN = {
  sensor: 0, worker: 0, asset: 0, permit: 1,
  zone: 2, hazard: 3, rule: 3, intervention: 4,
};
const COL_X = [40, 250, 470, 720, 980];

const STATUS_SWATCH = {
  normal: "#37c871", warning: "#f5a524", critical: "#f04444", mitigated: "#35d0d6",
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
      position: { x: COL_X[col] ?? 470, y: 40 + idx * 92 },
      data: { ...n },
      type: "safety",
    };
  });
}

function SafetyNode({ data, selected }) {
  return (
    <div className={`rf-node st-${data.status} ntype-${data.type} ${selected ? "sel" : ""}`}>
      <div className="ntype">{data.type}</div>
      <div>{data.label}</div>
    </div>
  );
}

const nodeTypes = { safety: SafetyNode };

function edgeStyle(e) {
  if (e.cut) return { stroke: "#35d0d6", strokeWidth: 2.4, strokeDasharray: "5 3" };
  if (e.causal_path) return { stroke: "#f04444", strokeWidth: 2.2 };
  return { stroke: "#33404f", strokeWidth: 1.2 };
}

function InnerGraph({ graph, filters }) {
  const [selected, setSelected] = useState(null);
  const rf = useReactFlow();

  const visibleIds = useMemo(() => {
    const s = new Set();
    graph.nodes.forEach((n) => { if (filters.has(n.type)) s.add(n.id); });
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
          labelStyle: { fill: "#5f6f80", fontSize: 9, fontFamily: "monospace" },
          labelBgStyle: { fill: "#0a0e13", fillOpacity: 0.85 },
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
        <Background color="#1f2a37" gap={22} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => STATUS_SWATCH[n.data?.status] ?? "#33404f"}
          maskColor="rgba(10,14,19,0.7)"
          style={{ background: "#0e141c", border: "1px solid #1f2a37" }}
        />
      </ReactFlow>

      <div style={{ position: "absolute", bottom: 12, left: 12, zIndex: 6 }}>
        <button className="mini-btn" onClick={() => rf.fitView({ duration: 400 })}>
          fit-to-screen
        </button>
      </div>

      {selected && (
        <div className="inspector">
          <h4>
            {selected.kind === "node" ? "Node" : "Edge"} inspector
          </h4>
          {selected.kind === "node" ? (
            <>
              <div className="kv"><b>id</b><span className="mono">{selected.id}</span></div>
              <div className="kv"><b>type</b><span>{selected.type}</span></div>
              <div className="kv"><b>status</b><span className={`s-${selected.status}`}>{selected.status}</span></div>
              <div className="kv"><b>risk</b><span className="mono">{selected.risk?.toFixed?.(3) ?? selected.risk}</span></div>
              {selected.metadata?.confidence != null && (
                <div className="kv"><b>confidence</b><span className="mono">{selected.metadata.confidence}</span></div>
              )}
              {selected.metadata?.source_event && (
                <div className="kv"><b>info-class</b><span>{selected.metadata.source_event}</span></div>
              )}
              {selected.metadata?.updated_at && (
                <div className="kv"><b>updated</b><span className="mono" style={{ fontSize: 10 }}>{String(selected.metadata.updated_at).slice(11, 19)}</span></div>
              )}
              <div className="kv"><b>in causal path</b><span>{String(selected.metadata?.in_causal_path ?? false)}</span></div>
              <div className="kv"><b>in cut</b><span>{String(selected.metadata?.cut ?? false)}</span></div>
              {Object.entries(selected.metadata || {})
                .filter(([k]) => !["in_causal_path", "cut", "source_event", "confidence", "updated_at", "created_at"].includes(k))
                .slice(0, 8)
                .map(([k, v]) => (
                  <div className="kv" key={k}><b>{k}</b><span className="mono" style={{ fontSize: 10 }}>{String(v)}</span></div>
                ))}
            </>
          ) : (
            <>
              <div className="kv"><b>id</b><span className="mono" style={{ fontSize: 10 }}>{selected.id}</span></div>
              <div className="kv"><b>relation</b><span>{selected.relation}</span></div>
              <div className="kv"><b>source</b><span className="mono">{selected.source}</span></div>
              <div className="kv"><b>target</b><span className="mono">{selected.target}</span></div>
              <div className="kv"><b>causal path</b><span>{String(selected.causal_path)}</span></div>
              <div className="kv"><b>cut by intervention</b><span className={selected.cut ? "s-mitigated" : ""}>{String(selected.cut)}</span></div>
            </>
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
    <div className="panel">
      <div className="panel-title">Interactive Safety Hypergraph</div>

      <div className="filters">
        {FILTER_TYPES.map((t) => (
          <span key={t} className={`chip ${filters.has(t) ? "active" : ""}`} onClick={() => toggle(t)}>
            {t}
          </span>
        ))}
        <span className="chip" onClick={() => setFilters(new Set(FILTER_TYPES))}>reset filters</span>
      </div>

      <div className="graph-wrap">
        {loading ? (
          <div className="graph-loading">building hypergraph from scenario…</div>
        ) : error ? (
          <div className="graph-error">graph error: {String(error)}</div>
        ) : !graph || graph.nodes.length === 0 ? (
          <div className="graph-empty">
            <div>no graph yet</div>
            <div className="faint">run a scenario to generate the live safety hypergraph</div>
          </div>
        ) : (
          <ReactFlowProvider>
            <InnerGraph graph={graph} filters={filters} />
          </ReactFlowProvider>
        )}
      </div>

      <div className="legend">
        <span className="lk"><span className="sw" style={{ borderColor: "#37c871" }} />normal</span>
        <span className="lk"><span className="sw" style={{ borderColor: "#f5a524" }} />warning</span>
        <span className="lk"><span className="sw" style={{ borderColor: "#f04444" }} />critical</span>
        <span className="lk"><span className="sw" style={{ borderColor: "#35d0d6" }} />mitigated</span>
        <span className="lk"><span className="sw" style={{ borderColor: "#f04444", background: "#f04444" }} />causal path</span>
        <span className="lk"><span className="sw" style={{ borderColor: "#35d0d6", borderStyle: "dashed" }} />minimum cut</span>
      </div>
    </div>
  );
}
