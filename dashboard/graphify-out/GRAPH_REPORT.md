# Graph Report - dashboard  (2026-08-22)

## Corpus Check
- 35 files · ~25,099 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 162 nodes · 249 edges · 14 communities (12 shown, 2 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS · INFERRED: 1 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b0615e36`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- devDependencies
- App.jsx
- api.js
- ResultsDashboard.jsx
- dependencies
- SimulationView.jsx
- ProgressSocket
- HypergraphView.jsx
- package.json
- BlueprintCanvas.jsx
- React + Vite
- vercel.json

## God Nodes (most connected - your core abstractions)
1. `API` - 13 edges
2. `ProgressSocket` - 12 edges
3. `useAuth()` - 7 edges
4. `BlueprintCanvas()` - 6 edges
5. `scripts` - 5 edges
6. `FactoryMapView()` - 4 edges
7. `App()` - 3 edges
8. `FactoryMap()` - 3 edges
9. `InnerGraph()` - 3 edges
10. `ModelStatus()` - 3 edges

## Surprising Connections (you probably didn't know these)
- `App()` --calls--> `useAuth()`  [EXTRACTED]
  src/App.jsx → src/context/AuthContext.jsx
- `LoginPage()` --calls--> `useAuth()`  [EXTRACTED]
  src/components/views/LoginPage.jsx → src/context/AuthContext.jsx
- `OnboardingFlow()` --calls--> `useAuth()`  [EXTRACTED]
  src/components/views/OnboardingFlow.jsx → src/context/AuthContext.jsx

## Import Cycles
- None detected.

## Communities (14 total, 2 thin omitted)

### Community 0 - "devDependencies"
Cohesion: 0.09
Nodes (23): eslint, @eslint/js, eslint-plugin-react-hooks, eslint-plugin-react-refresh, globals, devDependencies, eslint, @eslint/js (+15 more)

### Community 1 - "App.jsx"
Cohesion: 0.16
Nodes (13): App(), ChatDrawer(), Sidebar(), TopHeader(), INDUSTRY_TYPES, LoginPage(), INDUSTRY_HAZARD_DEFAULTS, OnboardingFlow() (+5 more)

### Community 2 - "api.js"
Cohesion: 0.14
Nodes (13): API, DEV_API_KEY, envelope(), json(), TERMINAL_STAGES, WS_BASE, ModelStatus(), ApprovalsView() (+5 more)

### Community 3 - "ResultsDashboard.jsx"
Cohesion: 0.17
Nodes (8): COLORS, FactoryMap(), getRiskColor(), FactoryMapView(), ModelProvenance(), ResultsDashboard(), CommandCenterView(), PlantStateView()

### Community 4 - "dependencies"
Cohesion: 0.13
Nodes (15): dagre, lucide-react, dependencies, dagre, lucide-react, plotly.js, react, react-dom (+7 more)

### Community 5 - "SimulationView.jsx"
Cohesion: 0.22
Nodes (9): ExecutionStatus(), STAGES, HYD_SENSORS, ModelInputPanel(), blankEntity(), EMPTY_SCENARIO, ENTITY_TABS, ScenarioBuilder() (+1 more)

### Community 7 - "HypergraphView.jsx"
Cohesion: 0.24
Nodes (8): edgeStyle(), FILTER_TYPES, getLayoutedElements(), HypergraphView(), InnerGraph(), nodeTypes, STATUS_SWATCH, RiskPathsView()

### Community 8 - "package.json"
Cohesion: 0.20
Nodes (9): name, private, scripts, build, dev, lint, preview, type (+1 more)

### Community 9 - "BlueprintCanvas.jsx"
Cohesion: 0.29
Nodes (9): BlueprintCanvas(), HAZARD_CLASSES, HAZARD_COLORS, nextSensorId(), nextZoneId(), normalizeSensors(), normalizeZones(), SENSOR_ICONS (+1 more)

### Community 10 - "React + Vite"
Cohesion: 0.50
Nodes (3): Expanding the ESLint configuration, React Compiler, React + Vite

## Knowledge Gaps
- **48 isolated node(s):** `name`, `private`, `version`, `type`, `dev` (+43 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ProgressSocket` connect `ProgressSocket` to `App.jsx`, `api.js`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `devDependencies` connect `devDependencies` to `package.json`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Why does `dependencies` connect `dependencies` to `package.json`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **What connects `name`, `private`, `version` to the rest of the system?**
  _48 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `devDependencies` be split into smaller, more focused modules?**
  _Cohesion score 0.08695652173913043 - nodes in this community are weakly interconnected._
- **Should `api.js` be split into smaller, more focused modules?**
  _Cohesion score 0.14285714285714285 - nodes in this community are weakly interconnected._
- **Should `dependencies` be split into smaller, more focused modules?**
  _Cohesion score 0.13333333333333333 - nodes in this community are weakly interconnected._