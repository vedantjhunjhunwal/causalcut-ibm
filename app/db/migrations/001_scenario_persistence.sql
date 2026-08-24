-- Migration 1.1.0: scenario persistence
-- Run this in your Supabase SQL editor (Dashboard > SQL Editor).
-- Safe to re-run: all CREATE statements use IF NOT EXISTS / ON CONFLICT DO NOTHING.
--
-- SECURITY MODEL:
--   Both tables have RLS enabled. No anon/authenticated policies are defined,
--   so direct client access is blocked entirely. The FastAPI backend uses the
--   service_role key, which bypasses RLS and retains full access.
--   This is the correct pattern for safety-critical backend-owned tables.

-- -----------------------------------------------------------------------
-- SCENARIOS — persisted scenario definitions [S]
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id       TEXT PRIMARY KEY,
    factory_id        TEXT NOT NULL,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    payload_json      TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    information_class TEXT NOT NULL DEFAULT 'S'
);

CREATE INDEX IF NOT EXISTS idx_scenarios_factory
    ON scenarios (factory_id, created_at DESC);

-- Enable RLS: no anon or authenticated key may read/write this table directly.
ALTER TABLE scenarios ENABLE ROW LEVEL SECURITY;

-- Service-role bypasses RLS automatically; no explicit policy needed.
-- The policy below documents the intent explicitly for auditors.
CREATE POLICY "backend_service_role_only" ON scenarios
    AS RESTRICTIVE
    TO service_role
    USING (true)
    WITH CHECK (true);

-- -----------------------------------------------------------------------
-- SCENARIO_RUNS — one row per pipeline execution [P]
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenario_runs (
    run_id            TEXT PRIMARY KEY,
    scenario_id       TEXT NOT NULL REFERENCES scenarios(scenario_id),
    factory_id        TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('completed','failed','running')),
    execution_mode    TEXT,
    activated_rules   JSONB NOT NULL DEFAULT '[]',
    causal_paths      JSONB NOT NULL DEFAULT '[]',
    recommendation    JSONB,
    residual_risk     FLOAT,
    processed_events  INTEGER NOT NULL DEFAULT 0,
    models_ran        JSONB,
    failure_reason    TEXT,
    pipeline_json     JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_scenario_runs_scenario
    ON scenario_runs (scenario_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_factory
    ON scenario_runs (factory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_status
    ON scenario_runs (status, created_at DESC);

-- Enable RLS on scenario_runs as well.
ALTER TABLE scenario_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "backend_service_role_only" ON scenario_runs
    AS RESTRICTIVE
    TO service_role
    USING (true)
    WITH CHECK (true);

