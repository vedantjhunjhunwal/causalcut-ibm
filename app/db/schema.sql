-- CAUSALCUT state store (SQLite, WAL mode)
-- Design doc §3.1: EVENT STORE (append-only) + PLANT-STATE STORE (materialized view)
-- MVP uses SQLite; every table here is Postgres-portable by design.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- EVENT STORE — append-only. No UPDATE, no DELETE. Ever.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    event_id          TEXT PRIMARY KEY,                 -- uuid4, idempotency key
    factory_id        TEXT NOT NULL,
    zone_id           TEXT NOT NULL,
    event_type        TEXT NOT NULL,
    worker_id         TEXT,
    asset_id          TEXT,
    event_time        TEXT NOT NULL,                    -- ISO8601 UTC
    ingest_time       TEXT NOT NULL,
    expires_at        TEXT NOT NULL,                    -- event_time + validity_window
    validity_window_s INTEGER NOT NULL,
    value_json        TEXT NOT NULL,
    severity          REAL NOT NULL CHECK (severity BETWEEN 0 AND 1),
    confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    uncertainty       REAL NOT NULL CHECK (uncertainty BETWEEN 0 AND 1),
    source            TEXT NOT NULL,
    model_version     TEXT,
    provenance        TEXT,
    information_class TEXT NOT NULL CHECK (information_class IN ('M','P','S','C','R','H')),
    synthetic_flag    INTEGER NOT NULL CHECK (synthetic_flag IN (0,1)),
    schema_version    TEXT NOT NULL,
    correlation_id    TEXT,
    payload_hash      TEXT NOT NULL,
    processed         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_zone_time   ON events (zone_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_type_time   ON events (event_type, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_worker      ON events (worker_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_asset       ON events (asset_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_corr        ON events (correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_hash        ON events (payload_hash, event_time);
CREATE INDEX IF NOT EXISTS idx_events_unprocessed ON events (processed, ingest_time);

-- Enforce append-only at the storage layer, not by convention.
CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events table is append-only: DELETE is forbidden');
END;

-- ---------------------------------------------------------------------
-- DEAD LETTER — events that failed downstream processing (§3.1)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dead_letter (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT NOT NULL,
    correlation_id TEXT,
    failed_at      TEXT NOT NULL,
    consumer       TEXT NOT NULL,
    attempt        INTEGER NOT NULL DEFAULT 1,
    error_type     TEXT NOT NULL,
    error_detail   TEXT,
    payload_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dlq_event ON dead_letter (event_id);

-- ---------------------------------------------------------------------
-- PERMITS — synthetic permit-to-work registry [S]
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permits (
    permit_id         TEXT PRIMARY KEY,                 -- e.g. PTW-007
    factory_id        TEXT NOT NULL,
    zone_id           TEXT NOT NULL,
    permit_type       TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('active','suspended','closed','expired')),
    issued_to         TEXT,                             -- worker_id
    issued_by         TEXT,                             -- SO-A / SM-01
    valid_from        TEXT NOT NULL,
    valid_to          TEXT NOT NULL,
    conditions_json   TEXT NOT NULL DEFAULT '{}',
    information_class TEXT NOT NULL DEFAULT 'S',
    synthetic_flag    INTEGER NOT NULL DEFAULT 1,
    updated_at        TEXT NOT NULL,
    last_event_id     TEXT
);
CREATE INDEX IF NOT EXISTS idx_permits_zone_status ON permits (zone_id, status);
CREATE INDEX IF NOT EXISTS idx_permits_validity    ON permits (valid_from, valid_to);

-- ---------------------------------------------------------------------
-- WORKER ZONES — current occupancy + PPE state [M]
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS worker_zones (
    worker_id         TEXT PRIMARY KEY,                 -- e.g. W-003
    factory_id        TEXT NOT NULL,
    zone_id           TEXT,                             -- NULL = not on site
    entered_at        TEXT,
    last_seen_at      TEXT NOT NULL,
    ppe_json          TEXT NOT NULL DEFAULT '{}',       -- {"hard_hat": false, ...}
    ppe_compliant     INTEGER NOT NULL DEFAULT 1 CHECK (ppe_compliant IN (0,1)),
    detection_confidence REAL,
    camera_id         TEXT,
    information_class TEXT NOT NULL DEFAULT 'M',
    synthetic_flag    INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL,
    last_event_id     TEXT
);
CREATE INDEX IF NOT EXISTS idx_worker_zone      ON worker_zones (zone_id);
CREATE INDEX IF NOT EXISTS idx_worker_compliant ON worker_zones (ppe_compliant, zone_id);

-- Occupancy history — needed later for propagation + evacuation audit.
CREATE TABLE IF NOT EXISTS worker_zone_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id  TEXT NOT NULL,
    zone_id    TEXT,
    event_time TEXT NOT NULL,
    event_id   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wzh_worker ON worker_zone_history (worker_id, event_time DESC);

-- ---------------------------------------------------------------------
-- SENSOR TELEMETRY — latest reading per sensor + rolling window [M]
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_telemetry (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id         TEXT NOT NULL,                    -- GS-03, TEMP-01, PRESS-02
    factory_id        TEXT NOT NULL,
    zone_id           TEXT NOT NULL,
    sensor_kind       TEXT NOT NULL,                    -- gas | temperature | pressure | flow | vibration
    reading_time      TEXT NOT NULL,
    value_num         REAL,
    unit              TEXT,
    value_json        TEXT NOT NULL DEFAULT '{}',
    quality           REAL NOT NULL DEFAULT 1.0 CHECK (quality BETWEEN 0 AND 1),
    stale             INTEGER NOT NULL DEFAULT 0 CHECK (stale IN (0,1)),
    drift_flag        INTEGER NOT NULL DEFAULT 0 CHECK (drift_flag IN (0,1)),
    information_class TEXT NOT NULL DEFAULT 'M',
    synthetic_flag    INTEGER NOT NULL DEFAULT 0,
    event_id          TEXT NOT NULL,
    UNIQUE (sensor_id, reading_time, event_id)
);
CREATE INDEX IF NOT EXISTS idx_telemetry_sensor_time ON sensor_telemetry (sensor_id, reading_time DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_zone_time   ON sensor_telemetry (zone_id, reading_time DESC);

-- Fast "current value of every sensor" lookup for the Plant-State Store.
CREATE TABLE IF NOT EXISTS sensor_latest (
    sensor_id     TEXT PRIMARY KEY,
    factory_id    TEXT,
    zone_id       TEXT NOT NULL,
    sensor_kind   TEXT NOT NULL,
    reading_time  TEXT NOT NULL,
    value_num     REAL,
    unit          TEXT,
    stale         INTEGER NOT NULL DEFAULT 0,
    drift_flag    INTEGER NOT NULL DEFAULT 0,
    event_id      TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sensor_latest_zone ON sensor_latest (zone_id);

-- ---------------------------------------------------------------------
-- BARRIERS — fire suppression, gas isolation, guards, LOTO [M]
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS barriers (
    barrier_id    TEXT PRIMARY KEY,                     -- FW-01, ESD-01, GAS-ISO-1
    zone_id       TEXT NOT NULL,
    barrier_type  TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('active','degraded','failed','unknown')),
    updated_at    TEXT NOT NULL,
    last_event_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_barriers_zone ON barriers (zone_id);

-- ---------------------------------------------------------------------
-- ZONE STATE — materialized rollup, rewritten by consumers
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zone_state (
    zone_id             TEXT PRIMARY KEY,
    factory_id          TEXT NOT NULL,
    risk_score          REAL NOT NULL DEFAULT 0.0,
    risk_info_class     TEXT NOT NULL DEFAULT 'P',
    ventilation_status  TEXT NOT NULL DEFAULT 'unknown',
    worker_count        INTEGER NOT NULL DEFAULT 0,
    active_permit_count INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- SCENARIOS — persisted scenario definitions [S]
-- Stores the full JSON submitted by the operator so any run can be
-- replayed, audited, or compared against future runs.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id   TEXT PRIMARY KEY,                     -- from Scenario.scenario_id
    factory_id    TEXT NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    payload_json  TEXT NOT NULL,                        -- full Scenario JSON (immutable)
    created_at    TEXT NOT NULL,
    information_class TEXT NOT NULL DEFAULT 'S'
);
CREATE INDEX IF NOT EXISTS idx_scenarios_factory ON scenarios (factory_id, created_at DESC);

-- ---------------------------------------------------------------------
-- SCENARIO RUNS — one row per execution of a scenario [P]
-- Stores the pipeline output: activated rules, causal paths,
-- recommendation, residual risk, and audit linkage.
-- A single scenario_id can have many runs (re-runs, what-if comparisons).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenario_runs (
    run_id            TEXT PRIMARY KEY,                 -- "run-{hex10}"
    scenario_id       TEXT NOT NULL REFERENCES scenarios(scenario_id),
    factory_id        TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('completed','failed','running')),
    execution_mode    TEXT,                             -- 'real' | 'mock' | 'degraded'
    activated_rules   TEXT NOT NULL DEFAULT '[]',       -- JSON array of rule template_ids
    causal_paths      TEXT NOT NULL DEFAULT '[]',       -- JSON array (serialized AccidentPath)
    recommendation    TEXT,                             -- JSON object (CutRecommendation) or NULL
    residual_risk     REAL,                             -- extracted from recommendation for fast query
    processed_events  INTEGER NOT NULL DEFAULT 0,
    models_ran        TEXT,                             -- JSON array of model names
    failure_reason    TEXT,                             -- NULL on success
    pipeline_json     TEXT,                             -- full pipeline metadata JSON
    created_at        TEXT NOT NULL,
    completed_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_scenario ON scenario_runs (scenario_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_factory  ON scenario_runs (factory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_status   ON scenario_runs (status, created_at DESC);

-- ---------------------------------------------------------------------
-- SCHEMA VERSIONING
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_migrations (version, applied_at)
VALUES ('1.0.0', datetime('now'));
INSERT OR IGNORE INTO schema_migrations (version, applied_at)
VALUES ('1.1.0-scenario-persistence', datetime('now'));
