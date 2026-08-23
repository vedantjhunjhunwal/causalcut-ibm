"""Runtime configuration for CAUSALCUT.

All values are overridable via environment variables or a local `.env` file.
Env prefix: CAUSALCUT_  (e.g. CAUSALCUT_DB_PATH=/data/causalcut.db)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAUSALCUT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Identity -------------------------------------------------------
    app_name: str = "CAUSALCUT"
    app_description: str = (
        "Minimum-Causal-Cut Safety Twin — canonical safety event ingestion, "
        "plant-state store and async processing spine."
    )
    version: str = "0.1.0"
    factory_id: str = "steelforge-001"
    environment: str = Field(default="dev", description="dev | staging | prod")

    # --- HTTP -----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:4000", "http://localhost:5173"]
    max_request_bytes: int = 2 * 1024 * 1024  # 2 MiB body ceiling
    request_timeout_seconds: float = 60.0


    # --- Persistence ----------------------------------------------------
    db_path: Path = Path("./data/causalcut.db")
    sqlite_busy_timeout_ms: int = 5_000
    sqlite_synchronous: str = "NORMAL"  # NORMAL is correct + fast under WAL

    # --- Queue ----------------------------------------------------------
    queue_max_size: int = 10_000
    queue_consumer_count: int = 2
    queue_put_timeout_seconds: float = 0.5
    dead_letter_max_retries: int = 3

    # --- Risk engine + gateway (analytical half) -----------------------
    safety_threshold: float = 0.15          # residual-risk ceiling for a cut
    audit_base_path: str = "./data/audit"   # write-ahead approval log
    handover_ack_grace_min: int = 15
    # Operators: "id:role:key,..." — if unset, dev keys are used (see gateway).
    operators: str | None = None

    # --- Scenario pipeline ---------------------------------------------
    # How long /scenario/run waits for its events to traverse the queue and be
    # projected into SQLite before analysis begins.
    scenario_pipeline_timeout_s: float = 30.0

    # --- Model inference layer -----------------------------------------
    # Execution mode for the model services. "auto" = real where artifacts +
    # deps are available, degraded otherwise. "mock" is for tests only and is
    # NEVER selected implicitly in the scenario workflow.
    model_execution_mode: str = Field(default="auto", description="auto | real | degraded | mock")
    model_confidence_threshold: float = 0.5
    model_device: str = "cpu"               # cpu | cuda
    model_request_timeout_s: float = 10.0
    model_retry_count: int = 1
    model_retry_backoff_s: float = 0.25
    # Artifact paths (defaults resolve under the repo root; override in prod).
    gas_xgb_model_path: str | None = None
    gas_isoforest_model_path: str | None = None
    hydraulic_model_dir: str | None = None
    machine_model_dir: str | None = None
    vision_model_path: str | None = None
    # Optional remote model service URLs (if models are separate services).
    gas_model_api_url: str | None = None
    machine_model_api_url: str | None = None
    hydraulic_model_api_url: str | None = None
    vision_model_api_url: str | None = None
    tracking_model_api_url: str | None = None
    rag_model_api_url: str | None = None


    # --- Ingestion policy ----------------------------------------------
    ingest_batch_max: int = 500
    default_validity_window_seconds: int = 300  # PT5M per design doc §5.1
    stale_event_grace_seconds: int = 60
    future_event_tolerance_seconds: int = 30

    # --- Logging --------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True

    # --- Security -------------------------------------------------------
    api_key: str | None = None  # if set, required on write endpoints
    docs_enabled: bool = True

    # --- Agentic AI (read-only Safety Intelligence chat) -----------------
    # Off by default: ships dark until a deployment deliberately turns it on.
    # The agent can only READ (plant state, risk engine, models, audit log,
    # regulatory corpus) — see app/engine/agent_tools.py. It cannot approve
    # or dispatch anything; that stays behind /risk/approve.
    agent_enabled: bool = False
    gemini_api_key: str | None = None
    # Model name is fully configurable since availability changes over time —
    # verify current model names in Google AI Studio / the Gemini API docs
    # before deploying. "gemini-2.0-flash" is a safe, widely-available default;
    # override with e.g. CAUSALCUT_AGENT_MODEL_NAME if a newer flash-tier
    # model is available to your API key.
    agent_model_name: str = "gemini-2.0-flash"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
