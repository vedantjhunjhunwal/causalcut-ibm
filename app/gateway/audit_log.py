"""Write-ahead audit log for operator decisions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.session import get_db

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
    def __init__(self, base_path: str = "data/audit") -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._last_hash = GENESIS_HASH
        self._recover()

    def _recover(self) -> None:
        try:
            db = get_db()
            if db.client:
                res = db.client.table("audit_log").select("seq, record_hash").order("seq", desc=True).limit(1).execute()
                if res.data:
                    self._seq = res.data[0]["seq"]
                    self._last_hash = res.data[0]["record_hash"]
                    logger.info("audit log recovered at seq=%d", self._seq)
        except Exception as e:
            logger.warning("failed to recover audit log from supabase: %s", e)

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

            data = {
                "seq": record.seq,
                "timestamp": record.timestamp,
                "correlation_id": record.correlation_id,
                "recommendation_id": record.recommendation_id,
                "approver_id": record.approver_id,
                "approver_role": record.approver_role,
                "decision": record.decision,
                "reason": record.reason,
                "interventions": json.dumps(record.interventions),
                "residual_risk": record.residual_risk,
                "prev_hash": record.prev_hash,
                "record_hash": record.record_hash,
            }

            db = get_db()
            if db.client:
                db.client.table("audit_log").insert(data).execute()

            self._last_hash = record.record_hash
            logger.info(
                "AUDIT seq=%d %s by %s on %s",
                record.seq, record.decision, record.approver_id, record.recommendation_id,
            )
            return record

    def verify_chain(self) -> tuple[bool, Optional[int]]:
        db = get_db()
        if not db.client:
            return False, 0
            
        res = db.client.table("audit_log").select("*").order("seq").execute()
        rows = res.data

        prev = GENESIS_HASH
        for d in rows:
            rec = AuditRecord(
                seq=d["seq"], timestamp=d["timestamp"], correlation_id=d["correlation_id"],
                recommendation_id=d["recommendation_id"], approver_id=d["approver_id"],
                approver_role=d["approver_role"], decision=d["decision"], reason=d["reason"],
                interventions=json.loads(d["interventions"]) if isinstance(d["interventions"], str) else d["interventions"],
                residual_risk=d["residual_risk"],
                prev_hash=d["prev_hash"],
            )
            if rec.prev_hash != prev or rec.compute_hash() != d["record_hash"]:
                return False, d["seq"]
            prev = d["record_hash"]
        return True, None

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        db = get_db()
        if not db.client:
            return []
            
        res = db.client.table("audit_log").select("*").order("seq", desc=True).limit(n).execute()
        out = res.data
        for r in out:
            if isinstance(r.get("interventions"), str):
                r["interventions"] = json.loads(r["interventions"])
        return out

