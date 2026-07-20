"""SQLite access layer, WAL-configured.

WAL matters here for a specific reason: the ingest path writes continuously
while the dashboard and (soon) the hypergraph engine read continuously. Under
the default rollback journal, every writer blocks every reader. Under WAL,
readers never block and the writer never blocks them — which is exactly the
read-heavy/write-steady shape of a safety twin.

One writer connection guarded by a lock (SQLite serialises writes anyway; an
explicit lock turns 'SQLITE_BUSY' surprises into orderly waiting) and a separate
reader connection.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Iterable
from typing_extensions import Self

import aiosqlite

from app.core.logging import get_logger

log = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(
        self,
        path: Path,
        busy_timeout_ms: int = 5_000,
        synchronous: str = "NORMAL",
    ) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self.synchronous = synchronous
        self._write: aiosqlite.Connection | None = None
        self._read: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._write = await self._open()
        self._read = await self._open(readonly_intent=True)
        await self._apply_schema()

        mode = await self.fetch_val("PRAGMA journal_mode")
        if str(mode).lower() != "wal":
            raise RuntimeError(f"expected WAL journal mode, got {mode!r}")
        log.info(
            "database ready",
            extra={"db_path": str(self.path), "journal_mode": mode},
        )
        return self

    async def _open(self, readonly_intent: bool = False) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path, isolation_level=None)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        await conn.execute(f"PRAGMA synchronous={self.synchronous}")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA temp_store=MEMORY")
        await conn.execute("PRAGMA cache_size=-16000")  # ~16 MB page cache
        if not readonly_intent:
            await conn.execute("PRAGMA wal_autocheckpoint=1000")
        return conn

    async def _apply_schema(self) -> None:
        assert self._write is not None
        ddl = _SCHEMA_PATH.read_text()
        async with self._write_lock:
            await self._write.executescript(ddl)

    async def close(self) -> None:
        for conn in (self._read, self._write):
            if conn is not None:
                await conn.close()
        self._read = self._write = None
        log.info("database closed")

    # ------------------------------------------------------------------ #
    # Reads (never blocked by the writer, thanks to WAL)
    # ------------------------------------------------------------------ #
    async def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        assert self._read is not None, "database not connected"
        async with self._read.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        assert self._read is not None, "database not connected"
        async with self._read.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def fetch_val(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = await self.fetch_one(sql, params)
        return next(iter(row.values())) if row else None

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        assert self._write is not None, "database not connected"
        async with self._write_lock:
            cur = await self._write.execute(sql, tuple(params))
            return cur.rowcount

    async def execute_many(self, sql: str, seq: list[tuple]) -> None:
        assert self._write is not None, "database not connected"
        async with self._write_lock:
            await self._write.executemany(sql, seq)

    async def transaction(self, statements: list[tuple[str, tuple]]) -> None:
        """All-or-nothing write. Used by ingest so an event and its projection
        can never disagree."""
        assert self._write is not None, "database not connected"
        async with self._write_lock:
            await self._write.execute("BEGIN IMMEDIATE")
            try:
                for sql, params in statements:
                    await self._write.execute(sql, params)
                await self._write.execute("COMMIT")
            except Exception:
                await self._write.execute("ROLLBACK")
                raise

    async def health(self) -> dict[str, Any]:
        return {
            "connected": self._write is not None,
            "journal_mode": await self.fetch_val("PRAGMA journal_mode"),
            "events": await self.fetch_val("SELECT COUNT(*) FROM events"),
            "dead_letter": await self.fetch_val("SELECT COUNT(*) FROM dead_letter"),
        }


_db: Database | None = None


def set_db(db: Database | None) -> None:
    global _db
    _db = db


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("database not initialised — app lifespan did not run")
    return _db
