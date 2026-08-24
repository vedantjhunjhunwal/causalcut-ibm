-- Migration 1.2.0: audit_log persistence
-- Run this in your Supabase SQL editor (Dashboard > SQL Editor).

CREATE TABLE IF NOT EXISTS audit_log (
    seq               SERIAL PRIMARY KEY,
    timestamp         TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    recommendation_id TEXT NOT NULL,
    approver_id       TEXT NOT NULL,
    approver_role     TEXT NOT NULL,
    decision          TEXT NOT NULL,
    reason            TEXT NOT NULL,
    interventions     JSONB NOT NULL DEFAULT '[]',
    residual_risk     FLOAT,
    prev_hash         TEXT NOT NULL,
    record_hash       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_seq ON audit_log (seq DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_approver ON audit_log (approver_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_recommendation ON audit_log (recommendation_id);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "backend_service_role_only" ON audit_log
    AS RESTRICTIVE
    TO service_role
    USING (true)
    WITH CHECK (true);
