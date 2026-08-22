"""Run the CausalCut schema against Supabase PostgreSQL."""
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in .env")

SCHEMA_SQL = """
-- ============================================
-- Enable Extensions
-- ============================================
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- DOMAIN 1: Factories (multi-factory per user)
-- ============================================
CREATE TABLE IF NOT EXISTS factories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID,
    name            TEXT NOT NULL,
    location        TEXT,
    industry_type   TEXT NOT NULL DEFAULT 'steel'
                    CHECK (industry_type IN ('steel','oil_gas','chemical','mining','pharma','general')),
    safety_threshold REAL NOT NULL DEFAULT 0.15,
    config_json     JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- DOMAIN 2: User Profiles
-- ============================================
CREATE TABLE IF NOT EXISTS user_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_id         UUID,
    display_name    TEXT NOT NULL,
    email           TEXT,
    industry_name   TEXT,
    industry_type   TEXT NOT NULL DEFAULT 'steel'
                    CHECK (industry_type IN ('steel','oil_gas','chemical','mining','pharma','general')),
    role            TEXT NOT NULL DEFAULT 'admin'
                    CHECK (role IN ('viewer','operator','shift_officer','safety_manager','admin')),
    api_key_hash    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- DOMAIN 3: Factory Floors (multi-floor per factory)
-- ============================================
CREATE TABLE IF NOT EXISTS factory_floors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id      UUID NOT NULL REFERENCES factories(id) ON DELETE CASCADE,
    floor_number    INTEGER NOT NULL,
    floor_name      TEXT NOT NULL,
    elevation_m     REAL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (factory_id, floor_number)
);

-- ============================================
-- DOMAIN 4: Blueprints (per-floor)
-- ============================================
CREATE TABLE IF NOT EXISTS blueprints (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id      UUID NOT NULL REFERENCES factories(id) ON DELETE CASCADE,
    floor_id        UUID NOT NULL REFERENCES factory_floors(id) ON DELETE CASCADE,
    file_name       TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    mime_type       TEXT NOT NULL DEFAULT 'image/png',
    file_size_bytes BIGINT,
    width_px        INTEGER,
    height_px       INTEGER,
    extracted_json  JSONB,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    uploaded_by     UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- DOMAIN 5: Factory Zones (belong to a floor)
-- ============================================
CREATE TABLE IF NOT EXISTS factory_zones (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id      UUID NOT NULL REFERENCES factories(id) ON DELETE CASCADE,
    floor_id        UUID NOT NULL REFERENCES factory_floors(id) ON DELETE CASCADE,
    zone_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    hazard_class    TEXT NOT NULL DEFAULT 'general'
                    CHECK (hazard_class IN ('flammable','toxic','confined_space',
                                            'electrical','radiation','general')),
    baseline_gas_threshold_ppm REAL DEFAULT 200.0,
    ventilation_status TEXT DEFAULT 'nominal'
                    CHECK (ventilation_status IN ('nominal','degraded','failed')),
    x_norm          REAL,
    y_norm          REAL,
    w_norm          REAL,
    h_norm          REAL,
    color           TEXT,
    metadata_json   JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (factory_id, zone_id)
);

-- ============================================
-- DOMAIN 5b: Zone Adjacency
-- ============================================
CREATE TABLE IF NOT EXISTS zone_adjacency (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id      UUID NOT NULL REFERENCES factories(id) ON DELETE CASCADE,
    zone_a          TEXT NOT NULL,
    zone_b          TEXT NOT NULL,
    medium          TEXT NOT NULL DEFAULT 'doorway'
                    CHECK (medium IN ('doorway','ventilation_duct','utility_bus',
                                      'stairwell','elevator','pipe_rack','open')),
    cross_floor     BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (factory_id, zone_a, zone_b)
);

-- ============================================
-- DOMAIN 5c: Factory Sensors
-- ============================================
CREATE TABLE IF NOT EXISTS factory_sensors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id      UUID NOT NULL REFERENCES factories(id) ON DELETE CASCADE,
    sensor_id       TEXT NOT NULL,
    zone_id         TEXT NOT NULL,
    floor_id        UUID REFERENCES factory_floors(id),
    modality        TEXT NOT NULL DEFAULT 'gas',
    unit            TEXT DEFAULT 'ppm',
    x_norm          REAL,
    y_norm          REAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (factory_id, sensor_id)
);

-- ============================================
-- DOMAIN 6: Safety Events (append-only)
-- ============================================
CREATE TABLE IF NOT EXISTS events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id      UUID NOT NULL REFERENCES factories(id),
    zone_id         TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    worker_id       TEXT,
    asset_id        TEXT,
    event_time      TIMESTAMPTZ NOT NULL,
    ingest_time     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    validity_window_s INTEGER NOT NULL,
    value_json      JSONB NOT NULL,
    severity        REAL NOT NULL CHECK (severity BETWEEN 0 AND 1),
    confidence      REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    uncertainty     REAL NOT NULL CHECK (uncertainty BETWEEN 0 AND 1),
    source          TEXT NOT NULL,
    model_version   TEXT,
    provenance      TEXT,
    information_class TEXT NOT NULL CHECK (information_class IN ('M','P','S','C','R','H')),
    synthetic_flag  BOOLEAN NOT NULL DEFAULT FALSE,
    schema_version  TEXT NOT NULL DEFAULT '1.0.0',
    correlation_id  TEXT,
    payload_hash    TEXT NOT NULL,
    processed       BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_events_zone_time ON events (zone_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (event_type, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_corr ON events (correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_hash ON events (payload_hash, event_time);

-- Append-only enforcement
CREATE OR REPLACE FUNCTION prevent_event_delete() RETURNS TRIGGER AS $$
BEGIN RAISE EXCEPTION 'events table is append-only: DELETE is forbidden'; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS events_no_delete ON events;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION prevent_event_delete();

-- ============================================
-- DOMAIN 7: Plant State Projections
-- ============================================
CREATE TABLE IF NOT EXISTS permits (
    permit_id       TEXT NOT NULL,
    factory_id      UUID NOT NULL REFERENCES factories(id),
    zone_id         TEXT NOT NULL,
    permit_type     TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('active','suspended','closed','expired')),
    issued_to       TEXT,
    issued_by       TEXT,
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ NOT NULL,
    conditions_json JSONB NOT NULL DEFAULT '{}',
    information_class TEXT NOT NULL DEFAULT 'S',
    synthetic_flag  BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_event_id   UUID,
    PRIMARY KEY (factory_id, permit_id)
);

CREATE TABLE IF NOT EXISTS worker_zones (
    worker_id       TEXT NOT NULL,
    factory_id      UUID NOT NULL REFERENCES factories(id),
    zone_id         TEXT,
    entered_at      TIMESTAMPTZ,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ppe_json        JSONB NOT NULL DEFAULT '{}',
    ppe_compliant   BOOLEAN NOT NULL DEFAULT TRUE,
    detection_confidence REAL,
    camera_id       TEXT,
    information_class TEXT NOT NULL DEFAULT 'M',
    synthetic_flag  BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_event_id   UUID,
    PRIMARY KEY (factory_id, worker_id)
);

CREATE TABLE IF NOT EXISTS worker_zone_history (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    worker_id       TEXT NOT NULL,
    zone_id         TEXT,
    event_time      TIMESTAMPTZ NOT NULL,
    event_id        UUID NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wzh_worker ON worker_zone_history (worker_id, event_time DESC);

CREATE TABLE IF NOT EXISTS sensor_telemetry (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id       TEXT NOT NULL,
    factory_id      UUID NOT NULL REFERENCES factories(id),
    zone_id         TEXT NOT NULL,
    sensor_kind     TEXT NOT NULL,
    reading_time    TIMESTAMPTZ NOT NULL,
    value_num       REAL,
    unit            TEXT,
    value_json      JSONB NOT NULL DEFAULT '{}',
    quality         REAL NOT NULL DEFAULT 1.0 CHECK (quality BETWEEN 0 AND 1),
    stale           BOOLEAN NOT NULL DEFAULT FALSE,
    drift_flag      BOOLEAN NOT NULL DEFAULT FALSE,
    information_class TEXT NOT NULL DEFAULT 'M',
    synthetic_flag  BOOLEAN NOT NULL DEFAULT FALSE,
    event_id        UUID NOT NULL,
    UNIQUE (sensor_id, reading_time, event_id)
);

CREATE TABLE IF NOT EXISTS sensor_latest (
    sensor_id       TEXT NOT NULL,
    factory_id      UUID NOT NULL REFERENCES factories(id),
    zone_id         TEXT NOT NULL,
    sensor_kind     TEXT NOT NULL,
    reading_time    TIMESTAMPTZ NOT NULL,
    value_num       REAL,
    unit            TEXT,
    stale           BOOLEAN NOT NULL DEFAULT FALSE,
    drift_flag      BOOLEAN NOT NULL DEFAULT FALSE,
    event_id        UUID NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (factory_id, sensor_id)
);

CREATE TABLE IF NOT EXISTS barriers (
    barrier_id      TEXT NOT NULL,
    factory_id      UUID NOT NULL REFERENCES factories(id),
    zone_id         TEXT NOT NULL,
    barrier_type    TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('active','degraded','failed','unknown')),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_event_id   UUID,
    PRIMARY KEY (factory_id, barrier_id)
);

CREATE TABLE IF NOT EXISTS zone_state (
    zone_id         TEXT NOT NULL,
    factory_id      UUID NOT NULL REFERENCES factories(id),
    risk_score      REAL NOT NULL DEFAULT 0.0,
    risk_info_class TEXT NOT NULL DEFAULT 'P',
    ventilation_status TEXT NOT NULL DEFAULT 'unknown',
    worker_count    INTEGER NOT NULL DEFAULT 0,
    active_permit_count INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (factory_id, zone_id)
);

CREATE TABLE IF NOT EXISTS dead_letter (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id        UUID NOT NULL,
    correlation_id  TEXT,
    failed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumer        TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 1,
    error_type      TEXT NOT NULL,
    error_detail    TEXT,
    payload_json    JSONB NOT NULL
);

-- ============================================
-- DOMAIN 8: Scenarios & Runs
-- ============================================
CREATE TABLE IF NOT EXISTS scenarios (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id      UUID NOT NULL REFERENCES factories(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    scenario_json   JSONB NOT NULL,
    schema_version  TEXT NOT NULL DEFAULT '1.0.0',
    created_by      UUID,
    is_sample       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scenario_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id     UUID NOT NULL REFERENCES scenarios(id),
    factory_id      UUID NOT NULL REFERENCES factories(id),
    correlation_id  TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed','decided')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    result_json     JSONB,
    graph_json      JSONB,
    stages_json     JSONB NOT NULL DEFAULT '[]',
    decision_json   JSONB,
    error_message   TEXT,
    run_by          UUID
);

-- ============================================
-- DOMAIN 9: Audit Trail (hash-chained, immutable)
-- ============================================
CREATE TABLE IF NOT EXISTS audit_log (
    seq             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    factory_id      UUID NOT NULL REFERENCES factories(id),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    correlation_id  TEXT NOT NULL,
    recommendation_id TEXT NOT NULL,
    approver_id     TEXT NOT NULL,
    approver_role   TEXT NOT NULL,
    decision        TEXT NOT NULL CHECK (decision IN ('APPROVE','REJECT','DEFER')),
    reason          TEXT,
    interventions   JSONB NOT NULL DEFAULT '[]',
    residual_risk   REAL,
    prev_hash       TEXT NOT NULL,
    record_hash     TEXT NOT NULL
);

CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS TRIGGER AS $$
BEGIN RAISE EXCEPTION 'audit_log is immutable: no DELETE or UPDATE allowed'; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_no_delete ON audit_log;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
DROP TRIGGER IF EXISTS audit_no_update ON audit_log;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

-- ============================================
-- DOMAIN 10: Agent Chat History
-- ============================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID,
    factory_id      UUID REFERENCES factories(id),
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool_call','tool_result')),
    content         TEXT NOT NULL,
    tool_name       TEXT,
    tool_args_json  JSONB,
    tool_result_json JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_msg_session ON chat_messages (session_id, created_at);

-- ============================================
-- DOMAIN 11: Compliance Reports
-- ============================================
CREATE TABLE IF NOT EXISTS compliance_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id      UUID NOT NULL REFERENCES factories(id),
    report_type     TEXT NOT NULL CHECK (report_type IN 
                    ('compliance_audit','incident_analysis','shift_handover',
                     'regulatory_gap','risk_assessment')),
    title           TEXT NOT NULL,
    summary         TEXT,
    content_json    JSONB,
    storage_path    TEXT,
    generated_by    TEXT NOT NULL DEFAULT 'agent',
    chat_session_id UUID REFERENCES chat_sessions(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- DOMAIN 12: Regulatory Vector Embeddings (pgvector)
-- ============================================
CREATE TABLE IF NOT EXISTS regulatory_chunks (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_id          TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    title           TEXT NOT NULL,
    chunk_id        TEXT NOT NULL UNIQUE,
    content         TEXT NOT NULL,
    citation        TEXT,
    clause_ref      TEXT,
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    token_count     INTEGER,
    metadata_json   JSONB NOT NULL DEFAULT '{}',
    embedding       vector(768) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reg_embedding ON regulatory_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_reg_source ON regulatory_chunks (source_type);
CREATE INDEX IF NOT EXISTS idx_reg_doc ON regulatory_chunks (doc_id);

-- ============================================
-- SCHEMA VERSION
-- ============================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO schema_migrations (version) VALUES ('2.0.0')
ON CONFLICT (version) DO NOTHING;

NOTIFY pgrst, 'reload schema';
"""

print("Connecting to Supabase PostgreSQL...")
conn = psycopg2.connect(DATABASE_URL, sslmode="require")
conn.autocommit = True
cur = conn.cursor()

print("Running schema DDL...")
cur.execute(SCHEMA_SQL)

# Verify tables
cur.execute("""
    SELECT table_name FROM information_schema.tables 
    WHERE table_schema = 'public' 
    ORDER BY table_name;
""")
tables = [row[0] for row in cur.fetchall()]

print(f"\n✅ Schema applied successfully!")
print(f"📊 {len(tables)} tables created:")
for t in tables:
    print(f"   • {t}")

cur.close()
conn.close()
print("\n✅ Done! Supabase database is ready.")
