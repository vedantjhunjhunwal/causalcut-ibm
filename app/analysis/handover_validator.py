"""Shift-handover inconsistency validator.

Shift changeovers are a classic accident precursor: the outgoing crew leaves a
hot-work permit open, the incoming crew never acknowledges an active gas alarm,
and two hours later nobody owns the hazard. This validator compares the
outgoing shift's declared open state against the incoming shift's
acknowledgements and the live plant state, and emits a
``shift_inconsistency`` SafetyEvent for each gap it finds.

Rules implemented (design doc 4.5):
  * ORPHANED_PERMIT      -- a permit is still active in the plant but was not
                            handed over / acknowledged by the incoming shift.
  * UNACKED_ALARM        -- an open alarm from the outgoing shift is not in the
                            incoming shift's acknowledged set.
  * MISSING_INCOMING     -- handover has no incoming officer (no one took over).
  * STALE_HANDOVER       -- handover left unacknowledged past its grace window.

Deliverable for: "Async Queue Consumer & Inconsistency Check" (validator half).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.engine.hypergraph_wrapper import SafetyHypergraph
from app.engine.types import (
    EventType,
    InformationClass,
    SafetyEvent,
    ShiftHandover,
    Severity,
)

logger = logging.getLogger("causalcut.handover")


@dataclass
class Inconsistency:
    kind: str
    zone_id: str
    detail: str
    severity: float
    references: list[str]


class HandoverValidator:
    """Validates shift handovers against live plant state."""

    def __init__(
        self,
        graph: SafetyHypergraph,
        ack_grace_minutes: int = 15,
    ) -> None:
        self.graph = graph
        self.ack_grace = timedelta(minutes=ack_grace_minutes)

    def validate(self, handover: ShiftHandover) -> list[Inconsistency]:
        issues: list[Inconsistency] = []
        now = datetime.now(timezone.utc)

        # MISSING_INCOMING
        if not handover.incoming_officer:
            issues.append(Inconsistency(
                kind="MISSING_INCOMING",
                zone_id=handover.zone_id,
                detail=f"No incoming officer recorded for handover from {handover.outgoing_officer}.",
                severity=0.55,
                references=[handover.handover_id],
            ))

        # STALE_HANDOVER
        if not handover.acknowledged:
            age = now - handover.handover_time
            if age > self.ack_grace:
                issues.append(Inconsistency(
                    kind="STALE_HANDOVER",
                    zone_id=handover.zone_id,
                    detail=(
                        f"Handover {handover.handover_id} unacknowledged for "
                        f"{int(age.total_seconds() // 60)} min "
                        f"(grace {int(self.ack_grace.total_seconds() // 60)} min)."
                    ),
                    severity=0.45,
                    references=[handover.handover_id],
                ))

        # ORPHANED_PERMIT: live-active permit in the zone that the outgoing
        # shift declared open but which the incoming shift didn't acknowledge.
        live_active = set(self.graph.active_permits_in_zone(handover.zone_id)) \
            if self.graph.has_node(handover.zone_id) else set()
        declared = set(handover.open_permits)
        acked = set() if not handover.acknowledged else declared

        # A permit is orphaned if it's live-active AND (declared-but-unacked
        # OR not declared at all during handover).
        for permit_id in live_active:
            if permit_id in declared and permit_id not in acked:
                issues.append(Inconsistency(
                    kind="ORPHANED_PERMIT",
                    zone_id=handover.zone_id,
                    detail=f"Permit {permit_id} active in {handover.zone_id} but not acknowledged by incoming shift.",
                    severity=0.70,
                    references=[permit_id, handover.handover_id],
                ))
            elif permit_id not in declared:
                issues.append(Inconsistency(
                    kind="ORPHANED_PERMIT",
                    zone_id=handover.zone_id,
                    detail=f"Permit {permit_id} active in {handover.zone_id} but absent from handover record.",
                    severity=0.65,
                    references=[permit_id, handover.handover_id],
                ))

        # UNACKED_ALARM: outgoing open alarms not acknowledged.
        if not handover.acknowledged:
            for alarm in handover.open_alarms:
                issues.append(Inconsistency(
                    kind="UNACKED_ALARM",
                    zone_id=handover.zone_id,
                    detail=f"Open alarm {alarm} from outgoing shift not acknowledged.",
                    severity=0.50,
                    references=[alarm, handover.handover_id],
                ))

        if issues:
            logger.warning(
                "handover %s produced %d inconsistencies",
                handover.handover_id, len(issues),
            )
        return issues

    def to_events(self, handover: ShiftHandover, issues: list[Inconsistency]) -> list[SafetyEvent]:
        events: list[SafetyEvent] = []
        for issue in issues:
            events.append(SafetyEvent(
                zone_id=issue.zone_id,
                event_type=EventType.SHIFT_INCONSISTENCY,
                value={
                    "kind": issue.kind,
                    "detail": issue.detail,
                    "references": issue.references,
                    "handover_id": handover.handover_id,
                    "outgoing_shift": handover.outgoing_shift,
                    "incoming_shift": handover.incoming_shift,
                },
                severity=issue.severity,
                confidence=0.9,
                source="handover_validator",
                information_class=InformationClass.PREDICTED,
            ))
        return events

    async def validate_and_emit(self, handover: ShiftHandover, queue) -> list[SafetyEvent]:
        """Validate a handover and publish any inconsistency events."""
        issues = self.validate(handover)
        events = self.to_events(handover, issues)
        for ev in events:
            await queue.publish(ev)
        return events
