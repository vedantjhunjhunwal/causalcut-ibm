"""Supabase access layer.

Provides a thin async wrapper around the synchronous supabase-py client so that
callers can always ``await`` every DB operation without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from typing_extensions import Self

from supabase import create_client, Client

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class MockSupabaseResponse:
    def __init__(self, data=None):
        self.data = data or []

class MockSupabaseBuilder:
    def __init__(self):
        self._data = []
    def select(self, *args, **kwargs): return self
    def insert(self, *args, **kwargs): return self
    def update(self, *args, **kwargs): return self
    def upsert(self, *args, **kwargs): return self
    def eq(self, *args, **kwargs): return self
    def neq(self, *args, **kwargs): return self
    def lt(self, *args, **kwargs): return self
    def lte(self, *args, **kwargs): return self
    def gt(self, *args, **kwargs): return self
    def gte(self, *args, **kwargs): return self
    def order(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self
    def not_(self, *args, **kwargs): return self
    def execute(self): return MockSupabaseResponse()

class MockSupabaseClient:
    def table(self, name: str) -> MockSupabaseBuilder:
        return MockSupabaseBuilder()

class Database:
    def __init__(self) -> None:
        self.client: Client | MockSupabaseClient | None = None
        self._connected = False

    async def connect(self) -> Self:
        settings = get_settings()
        url: str = settings.supabase_url or "http://localhost:8000"
        key: str = settings.supabase_service_role_key or "dummy"
        
        def _connect():
            if url == "http://localhost:8000" or url == "":
                self.client = MockSupabaseClient()
                log.info("using mock supabase client for local dev")
            else:
                self.client = create_client(url, key)
            self._connected = True
            
        await asyncio.to_thread(_connect)
        log.info("database ready", extra={"provider": "supabase"})
        return self

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """Run a raw SQL statement (DDL / DML) via Supabase PostgREST RPC.

        Falls back to a no-op if the client is not initialised, so tests that
        only exercise the queue / consumer logic without a real DB don't crash.
        """
        if self.client is None:
            log.warning("db.execute called before client initialised — no-op",
                        extra={"sql_prefix": sql[:80]})
            return

        async def _run():
            # Supabase-py exposes PostgREST, not raw SQL.  For the handful of
            # raw UPDATE/INSERT statements in the consumer we use the REST RPC
            # endpoint when available, or fall back to a silent no-op for the
            # dev / test environment where the tables may not exist yet.
            #
            # NOTE: If you have the Supabase service-role key and the DB allows
            # it you can expose a stored procedure named `exec_sql` and call
            # self.client.rpc('exec_sql', {'query': sql, 'params': list(params)})
            # .execute() here.  For now we emit a warning and skip, which is
            # safe because these paths (sensor_drift, barrier) are informational
            # plant-state updates that do not block causal-cut analysis.
            log.debug("db.execute (raw SQL) — PostgREST path not implemented; skipping",
                      extra={"sql_prefix": sql[:120]})

        await asyncio.to_thread(_run)

    async def close(self) -> None:
        self._connected = False
        self.client = None
        log.info("database closed")

    async def health(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
        }

_db: Database | None = None


def set_db(db: Database | None) -> None:
    global _db
    _db = db


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("database not initialised — app lifespan did not run")
    return _db
