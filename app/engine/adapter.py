"""Adapter: canonical ``SafetyEvent`` -> engine-internal event.

The canonical schema (``app.schemas.canonical.SafetyEvent``) is the *external
contract* every producer speaks. The risk engine keeps its own internal domain
event (``app.engine.types.SafetyEvent``) so the graph/rules/optimiser code did
not have to be rewritten around the wire format. This function is the single,
well-tested seam between the two.

The only real remapping work:
  * canonical keeps ``sensor_id`` / ``permit_id`` inside ``value``; the engine
    wants them lifted to the top level.
  * canonical encodes PPE as ``value.ppe`` (item -> bool) or ``value.missing``
    (list); the engine reads ``value.missing_ppe`` (list of absent items).
Everything else (zone_id, event_type string values, severity, information
class letters) is already identical by construction.
"""

from __future__ import annotations

from app.engine.types import EventType as EngineEventType
from app.engine.types import InformationClass as EngineInfoClass
from app.engine.types import SafetyEvent as EngineEvent
from app.schemas.canonical import SafetyEvent as CanonicalEvent


def canonical_to_engine(e: CanonicalEvent) -> EngineEvent | None:
    """Convert one canonical event into the engine's domain event.

    Returns ``None`` for event types the engine has no handler for, so the
    caller can cheaply skip them.
    """
    etype = str(e.event_type)
    if etype not in EngineEventType._value2member_map_:
        return None

    value = dict(e.value)  # copy; we may normalise keys

    # Lift identifiers the engine expects at the top level.
    sensor_id = value.get("sensor_id")
    permit_id = value.get("permit_id")

    # Normalise PPE representation -> engine's `missing_ppe` list.
    if etype == EventType_PPE and "missing_ppe" not in value:
        if isinstance(value.get("ppe"), dict):
            value["missing_ppe"] = [k for k, ok in value["ppe"].items() if not ok]
        elif isinstance(value.get("missing"), list):
            value["missing_ppe"] = list(value["missing"])

    return EngineEvent(
        event_id=str(e.event_id),
        factory_id=e.factory_id,
        zone_id=str(e.zone_id),
        event_type=EngineEventType(etype),
        worker_id=e.worker_id,
        asset_id=e.asset_id,
        sensor_id=sensor_id,
        permit_id=permit_id,
        event_time=e.event_time,
        value=value,
        severity=e.severity,
        confidence=e.confidence,
        uncertainty=e.uncertainty,
        source=e.source,
        model_version=e.model_version,
        provenance=e.provenance,
        information_class=EngineInfoClass(str(e.information_class)),
        synthetic_flag=e.synthetic_flag,
        correlation_id=e.correlation_id,
    )


EventType_PPE = "ppe_violation"
