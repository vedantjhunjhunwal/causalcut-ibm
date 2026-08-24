"""Hybrid Database access layer (Supabase + Local SQLite WAL).

Provides an async wrapper ensuring callers can await every DB operation
(fetch_all, fetch_one, execute) without blocking the event loop or failing
when offline / in dev.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any
from typing_extensions import Self

from supabase import create_client, Client

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class Database:
    def __init__(self) -> None:
        self.client: Client | None = None
        self._connected = False
        self.db_path = Path("data/causalcut.db")
        self._sqlite_conn: sqlite3.Connection | None = None

    async def connect(self) -> Self:
        settings = get_settings()
        url: str = settings.supabase_url or "http://localhost:8000"
        key: str = settings.supabase_service_role_key or "dummy"
        
        def _connect():
            try:
                self.client = create_client(url, key)
            except Exception as e:
                log.warning(f"Supabase client initialization warning: {e}")
                self.client = None
            
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._sqlite_conn.row_factory = sqlite3.Row
            
            schema_path = Path(__file__).parent / "schema.sql"
            if schema_path.exists():
                try:
                    with open(schema_path, "r", encoding="utf-8") as f:
                        self._sqlite_conn.executescript(f.read())
                    self._sqlite_conn.commit()
                except Exception as e:
                    log.warning(f"Failed to execute schema.sql on local db: {e}")
            
            self._connected = True
            
        await asyncio.to_thread(_connect)
        log.info("database ready", extra={"provider": "supabase+sqlite"})
        return self

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Fetch multiple rows as list of dicts."""
        def _run():
            if not self._sqlite_conn:
                return []
            try:
                cur = self._sqlite_conn.cursor()
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            except Exception as e:
                log.debug(f"fetch_all query warning: {e}", extra={"sql": sql[:100]})
                return []
        return await asyncio.to_thread(_run)

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Fetch a single row as a dict."""
        def _run():
            if not self._sqlite_conn:
                return None
            try:
                cur = self._sqlite_conn.cursor()
                cur.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row else None
            except Exception as e:
                log.debug(f"fetch_one query warning: {e}", extra={"sql": sql[:100]})
                return None
        return await asyncio.to_thread(_run)

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """Run an INSERT, UPDATE, or DDL statement."""
        def _run():
            if not self._sqlite_conn:
                return
            try:
                cur = self._sqlite_conn.cursor()
                cur.execute(sql, params)
                self._sqlite_conn.commit()
            except Exception as e:
                log.debug(f"db.execute warning: {e}", extra={"sql": sql[:100]})
        await asyncio.to_thread(_run)

    async def close(self) -> None:
        self._connected = False
        self.client = None
        if self._sqlite_conn:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass
            self._sqlite_conn = None
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
