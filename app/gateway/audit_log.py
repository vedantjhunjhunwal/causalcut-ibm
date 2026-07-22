"""Write-ahead audit log for operator decisions.

Every approval, rejection or deferral is written to an append-only,
tamper-evident log *before* any downstream dispatch happens (write-ahead).
Each record is chained to the previous one by hash, so any silent edit or
deletion of history is detectable. The log is fsync'd on write so a crash
cannot lose an approved decision that was about to be executed.

This satisfies two design-doc requirements at once:
  * 3.x Human Approval Gateway -- "Logs decision with timestamp, approver_id,
    correlation_id"
  * 9.x MVP -- SQLite-backed durable store; the WAL file is the source of truth
    and can be replayed into SQLite.

Deliverable for: TARUN "operator audit logging".
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("causalcut.audit")

GENESIS_HASH = "0" * 64


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AuditRecord:
    seq: int
    timestamp: str
    correlation_id: str
    recommendation_id: str
    approver_id: str
    approver_role: str
    decision: str            # APPROVE | REJECT | DEFER
    reason: str
    interventions: list[str]
    residual_risk: Optional[float]
    prev_hash: str
    record_hash: str = ""

    def canonical_payload(self) -> str:
        d = asdict(self)
        d.pop("record_hash", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_payload().encode("utf-8")).hexdigest()


class AuditLog:
    """Append-only, hash-chained, write-ahead audit log.

    Two backing stores kept in lockstep:
      * a plain-text WAL file (``.wal``) -- written and fsync'd first;
      * a SQLite table -- the queryable materialised view.
    """

    def __init__(self, base_path: str = "data/audit") -> None:
        self.base = Path(base_path)
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.wal_path = self.base.with_suffix(".wal")
        self.db_path = self.base.with_suffix(".db")
        self._lock = threading.Lock()
        self._seq = 0
        self._last_hash = GENESIS_HASH
        self._init_db()
        self._recover()

    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS audit (
                seq INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                recommendation_id TEXT NOT NULL,
                approver_id TEXT NOT NULL,
                approver_role TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT,
                interventions TEXT,
                residual_risk REAL,
                prev_hash TEXT NOT NULL,
                record_hash TEXT NOT NULL
            )
            """
        )
        con.commit()
        con.close()

    def _recover(self) -> None:
        """Replay the WAL so seq/hash chain continues after a restart."""
        if not self.wal_path.exists():
            return
        last: Optional[dict] = None
        with self.wal_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = json.loads(line)
        if last:
            self._seq = last["seq"]
            self._last_hash = last["record_hash"]
            logger.info("audit log recovered at seq=%d", self._seq)

    def append(
        self,
        *,
        correlation_id: str,
        recommendation_id: str,
        approver_id: str,
        approver_role: str,
        decision: str,
        reason: str,
        interventions: list[str],
        residual_risk: Optional[float],
    ) -> AuditRecord:
        with self._lock:
            self._seq += 1
            record = AuditRecord(
                seq=self._seq,
                timestamp=_utcnow_iso(),
                correlation_id=correlation_id,
                recommendation_id=recommendation_id,
                approver_id=approver_id,
                approver_role=approver_role,
                decision=decision,
                reason=reason,
                interventions=interventions,
                residual_risk=residual_risk,
                prev_hash=self._last_hash,
            )
            record.record_hash = record.compute_hash()

            # 1) Write-ahead: append to WAL and fsync BEFORE anything else.
            with self.wal_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(record), sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())

            # 2) Materialise into SQLite.
            con = sqlite3.connect(self.db_path)
            con.execute(
                "INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.seq, record.timestamp, record.correlation_id,
                    record.recommendation_id, record.approver_id, record.approver_role,
                    record.decision, record.reason, json.dumps(record.interventions),
                    record.residual_risk, record.prev_hash, record.record_hash,
                ),
            )
            con.commit()
            con.close()

            self._last_hash = record.record_hash
            logger.info(
                "AUDIT seq=%d %s by %s on %s",
                record.seq, record.decision, record.approver_id, record.recommendation_id,
            )
            return record

    def verify_chain(self) -> tuple[bool, Optional[int]]:
        """Recompute the hash chain. Returns (ok, first_bad_seq)."""
        con = sqlite3.connect(self.db_path)
        rows = con.execute("SELECT * FROM audit ORDER BY seq").fetchall()
        cols = [c[0] for c in con.execute("SELECT * FROM audit LIMIT 0").description]
        con.close()

        prev = GENESIS_HASH
        for row in rows:
            d = dict(zip(cols, row))
            rec = AuditRecord(
                seq=d["seq"], timestamp=d["timestamp"], correlation_id=d["correlation_id"],
                recommendation_id=d["recommendation_id"], approver_id=d["approver_id"],
                approver_role=d["approver_role"], decision=d["decision"], reason=d["reason"],
                interventions=json.loads(d["interventions"]), residual_risk=d["residual_risk"],
                prev_hash=d["prev_hash"],
            )
            if rec.prev_hash != prev or rec.compute_hash() != d["record_hash"]:
                return False, d["seq"]
            prev = d["record_hash"]
        return True, None

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (n,)).fetchall()
        con.close()
        out = [dict(r) for r in rows]
        for r in out:
            r["interventions"] = json.loads(r["interventions"])
        return out
