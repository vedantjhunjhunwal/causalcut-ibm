"""Shared scenario schema — the single contract for user-defined incidents.

The frontend builder form, the JSON upload path, this backend API, and the
scenario replayer all speak *this* schema. A scenario is a declarative
description of a plant snapshot plus a timeline of events; ``to_events()``
lowers it into the canonical ``SafetyEvent`` stream that the rest of the
pipeline already consumes, so nothing downstream had to change.

Design-doc alignment: the field set mirrors §5 data contracts (zones, sensors,
workers, permits, ventilation, events, severity, confidence) while staying
fully user-authorable — no hardcoded Steelforge assumptions live here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.canonical import SafetyEvent
from app.schemas.enums import (
    EventType,
    InformationClass,
    ZoneIdStr,
)

SCENARIO_SCHEMA_VERSION = "1.0.0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_ID = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone_id: ZoneIdStr
    name: str = ""
    hazard_class: str = "standard"
    baseline_gas_threshold_ppm: float = Field(default=200.0, ge=0.0)
    ventilation_status: Literal["nominal", "degraded", "failed"] = "nominal"
    ventilation_flow_ratio: float = Field(default=1.0, ge=0.0, le=1.0)


class Adjacency(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone_a: ZoneIdStr
    zone_b: ZoneIdStr
    medium: str = "shared_utility"


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = _ID
    zone_id: ZoneIdStr
    asset_type: str = "generic"
    failure_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    condition: str = "nominal"


class Sensor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_id: str = _ID
    zone_id: ZoneIdStr
    modality: str = "gas"
    unit: str = "ppm"


class GasReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_id: str = _ID
    zone_id: ZoneIdStr
    gas_type: str = "ammonia"
    concentration_ppm: float = Field(ge=0.0)
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    offset_seconds: int = Field(default=0, ge=0)
    # Raw 128-dim UCI gas sensor array. When present, the trained gas model runs
    # REAL inference on it and its prediction (not these fields) becomes the
    # canonical event. When absent, the reading is treated as an operator
    # MEASURED value and the pipeline runs degraded for this sensor.
    features: list[float] | None = Field(default=None, min_length=128, max_length=128)


class MachineReading(BaseModel):
    """Raw AI4I machine-condition features -> trained machine-failure model."""
    model_config = ConfigDict(extra="forbid")
    asset_id: str = _ID
    zone_id: ZoneIdStr
    Type: str = "M"
    Air_temperature: float = 298.1
    Process_temperature: float = 308.6
    Rotational_speed: float = 1500.0
    Torque: float = 40.0
    Tool_wear: float = 0.0
    offset_seconds: int = Field(default=0, ge=0)


class VisionInput(BaseModel):
    """An image (or frame reference) to run through the real YOLO PPE model.

    Nothing is inferred client-side: the raw image goes to the shared vision
    service. If the checkpoint or torch/ultralytics are missing, the service
    reports unavailable and NO PPE event is fabricated.
    """
    model_config = ConfigDict(extra="forbid")
    zone_id: ZoneIdStr
    image_id: str = Field(default="frame-0", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
    # One of: base64 payload, a path/URL reference, or a video frame index.
    image_b64: str | None = None
    image_ref: str | None = None
    frame_id: int | None = Field(default=None, ge=0)
    worker_id: str | None = None
    offset_seconds: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _needs_a_source(self) -> "VisionInput":
        if not self.image_b64 and not self.image_ref:
            raise ValueError("vision input needs either image_b64 or image_ref")
        return self


class Detection(BaseModel):
    """A single detection handed to the tracker (validated shape)."""
    model_config = ConfigDict(extra="forbid")
    frame_id: int = Field(ge=0)
    bbox: list[float] = Field(min_length=4, max_length=4, description="[x, y, w, h]")
    object_class: str = Field(default="person", alias="class")
    confidence: float = Field(ge=0.0, le=1.0)
    track_id: int | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TrackingInput(BaseModel):
    """Detections to run through the real ByteTrack re-identification service."""
    model_config = ConfigDict(extra="forbid")
    zone_id: ZoneIdStr
    detections: list[Detection] = Field(default_factory=list)
    offset_seconds: int = Field(default=0, ge=0)


class HydraulicReading(BaseModel):
    """Raw per-sensor hydraulic cycle arrays -> trained hydraulic classifier."""
    model_config = ConfigDict(extra="forbid")
    zone_id: ZoneIdStr
    sensor_data: dict[str, list[float]] = Field(default_factory=dict)
    offset_seconds: int = Field(default=0, ge=0)


class Worker(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}$")
    zone_id: ZoneIdStr | None = None
    present: bool = True
    missing_ppe: list[str] = Field(default_factory=list)

    @field_validator("present", mode="before")
    @classmethod
    def _validate_present(cls, v: Any) -> Any:
        if isinstance(v, str):
            raise TypeError("Worker.present must be a boolean, not a string")
        return v


class Permit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permit_id: str = _ID
    zone_id: ZoneIdStr
    permit_type: str = "hot_work"
    status: Literal["active", "suspended", "closed", "expired"] = "active"
    worker_id: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_low = v.strip().lower()
            if v_low in ("active", "suspended", "closed", "expired"):
                return v_low
            if v_low == "inactive":
                return "closed"
        return v


class ScenarioEvent(BaseModel):
    """A timeline event. ``value`` is the canonical event body."""

    model_config = ConfigDict(extra="forbid")
    event_type: EventType
    zone_id: ZoneIdStr
    offset_seconds: int = Field(default=0, ge=0)
    worker_id: str | None = None
    asset_id: str | None = None
    sensor_id: str | None = None
    permit_id: str | None = None
    value: dict[str, Any] = Field(default_factory=dict)
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    information_class: InformationClass = InformationClass.MEASURED
    source: str = "scenario_builder"
    label: str = ""


class Scenario(BaseModel):
    """A complete, user-authorable factory-incident scenario."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    scenario_id: str = Field(default_factory=lambda: f"scn-{uuid.uuid4().hex[:8]}")
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    factory_id: str = "00000000-0000-0000-0000-000000000001"
    safety_threshold: float = Field(default=0.15, ge=0.0, le=1.0)

    @field_validator("safety_threshold", mode="before")
    @classmethod
    def _validate_safety_threshold(cls, v: Any) -> Any:
        if isinstance(v, str):
            raise TypeError("safety_threshold must be a float, not a string")
        return v

    @model_validator(mode="before")
    @classmethod
    def _check_scenario_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "schema_version" in data or "metadata" in data:
                if "scenario_id" not in data or data.get("scenario_id") is None:
                    raise ValueError("Field 'scenario_id' is required")
        return data
    # Anchor for event offsets. If omitted, the timeline is rebased so its LAST
    # event lands at "now" — a scenario describes a sequence leading up to the
    # present, not one starting now. Without this, positive offsets would place
    # events in the future and the ingestion boundary would (correctly) reject
    # them as producer clock skew.
    base_time: datetime | None = None

    zones: list[Zone] = Field(default_factory=list)
    zone_adjacency: list[Adjacency] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    sensors: list[Sensor] = Field(default_factory=list)
    gas_readings: list[GasReading] = Field(default_factory=list)
    machine_readings: list[MachineReading] = Field(default_factory=list)
    hydraulic_readings: list[HydraulicReading] = Field(default_factory=list)
    vision_inputs: list[VisionInput] = Field(default_factory=list)
    tracking_inputs: list[TrackingInput] = Field(default_factory=list)
    workers: list[Worker] = Field(default_factory=list)
    permits: list[Permit] = Field(default_factory=list)
    events: list[ScenarioEvent] = Field(default_factory=list)

    safety_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = SCENARIO_SCHEMA_VERSION

    # -------------------------------------------------------------- #
    @field_validator("zones")
    @classmethod
    def _at_least_one_zone(cls, v: list[Zone]) -> list[Zone]:
        if not v:
            raise ValueError("a scenario needs at least one zone")
        return v

    @model_validator(mode="after")
    def _referential_integrity(self) -> "Scenario":
        # The field validator above only fires when ``zones`` is actually
        # supplied — pydantic skips validators for defaulted fields — so a
        # payload that omits the key entirely would otherwise validate clean
        # and then fail deep in the pipeline with an IndexError. Catch it here,
        # where the check always runs.
        if not self.zones:
            raise ValueError("a scenario needs at least one zone")

        zone_ids = {z.zone_id for z in self.zones}
        problems: list[str] = []

        def check(kind: str, ident: str, zid: str | None) -> None:
            if zid is not None and zid not in zone_ids:
                problems.append(f"{kind} '{ident}' references unknown zone '{zid}'")

        for a in self.zone_adjacency:
            check("adjacency", f"{a.zone_a}<->{a.zone_b}", a.zone_a)
            check("adjacency", f"{a.zone_a}<->{a.zone_b}", a.zone_b)
        for s in self.sensors:
            check("sensor", s.sensor_id, s.zone_id)
        for asset in self.assets:
            check("asset", asset.asset_id, asset.zone_id)
        for g in self.gas_readings:
            check("gas_reading", g.sensor_id, g.zone_id)
        for w in self.workers:
            check("worker", w.worker_id, w.zone_id)
        for p in self.permits:
            check("permit", p.permit_id, p.zone_id)
        for m in self.machine_readings:
            check("machine_reading", m.asset_id, m.zone_id)
        for h in self.hydraulic_readings:
            check("hydraulic_reading", h.zone_id, h.zone_id)
        for v in self.vision_inputs:
            check("vision_input", v.image_id, v.zone_id)
        for t in self.tracking_inputs:
            check("tracking_input", "detections", t.zone_id)
        for i, e in enumerate(self.events):
            check("event", e.label or f"#{i}", e.zone_id)

        if problems:
            raise ValueError("; ".join(problems))
        return self

    # -------------------------------------------------------------- #
    @property
    def max_offset_seconds(self) -> int:
        offsets = [0]
        offsets += [g.offset_seconds for g in self.gas_readings]
        offsets += [m.offset_seconds for m in self.machine_readings]
        offsets += [h.offset_seconds for h in self.hydraulic_readings]
        offsets += [v.offset_seconds for v in self.vision_inputs]
        offsets += [t.offset_seconds for t in self.tracking_inputs]
        offsets += [e.offset_seconds for e in self.events]
        return max(offsets)

    @property
    def effective_base_time(self) -> datetime:
        """Anchor used for all event timestamps.

        Explicit ``base_time`` wins (replay of a recorded incident). Otherwise
        the timeline is rebased so the last event coincides with now.
        """
        if self.base_time is not None:
            return self.base_time
        return _utcnow() - timedelta(seconds=self.max_offset_seconds)

    def to_events(self) -> list[SafetyEvent]:
        """Lower this scenario into an ordered canonical event stream.

        Declarative state (workers present, permits active, gas readings) is
        emitted as t0 events, then the explicit timeline events follow, each
        stamped at ``base_time + offset_seconds``. Everything downstream
        (queue, projector, hypergraph, rules, optimiser) already consumes this.
        """
        events: list[SafetyEvent] = []
        anchor = self.effective_base_time

        def emit(
            *,
            event_type: str,
            zone_id: str,
            value: dict,
            offset: int,
            severity: float,
            confidence: float,
            info_class: InformationClass,
            source: str,
            worker_id: str | None = None,
            asset_id: str | None = None,
        ) -> None:
            ic = info_class
            synthetic = ic is InformationClass.SYNTHETIC
            # A model_version is only meaningful for genuine model output.
            # Events lowered here are user-entered facts (observed) or replay
            # inputs (synthetic), so they carry no model attribution — the
            # trained-model path sets model_version in engine/model_events.py.
            model_version = None
            uncertainty = 0.1 if ic is InformationClass.COUNTERFACTUAL else 0.0
            events.append(
                SafetyEvent(
                    factory_id=self.factory_id,
                    zone_id=zone_id,
                    event_type=event_type,  # type: ignore[arg-type]
                    worker_id=worker_id,
                    asset_id=asset_id,
                    event_time=anchor + timedelta(seconds=offset),
                    value=value,
                    severity=severity,
                    confidence=confidence,
                    uncertainty=uncertainty,
                    source=source,
                    model_version=model_version,
                    information_class=ic,
                    synthetic_flag=synthetic,
                )
            )

        # Declarative state -> t0 events.
        for w in self.workers:
            if w.zone_id and w.present:
                emit(event_type="worker_presence", zone_id=w.zone_id,
                     value={"present": True}, offset=0, severity=0.0,
                     confidence=1.0, info_class=InformationClass.MEASURED,
                     source="scenario_state", worker_id=w.worker_id)
            if w.missing_ppe:
                emit(event_type="ppe_violation", zone_id=w.zone_id or self.zones[0].zone_id,
                     value={"missing_ppe": list(w.missing_ppe)}, offset=0,
                     severity=0.5, confidence=0.9,
                     info_class=InformationClass.MEASURED, source="scenario_state",
                     worker_id=w.worker_id)

        for p in self.permits:
            if p.status == "active":
                emit(event_type="permit_status", zone_id=p.zone_id,
                     value={"permit_id": p.permit_id, "permit_type": p.permit_type,
                            "status": "active"},
                     offset=0, severity=0.1, confidence=1.0,
                     info_class=InformationClass.SYNTHETIC, source="scenario_state")

        for z in self.zones:
            if z.ventilation_status != "nominal" or z.ventilation_flow_ratio < 1.0:
                # Operator-entered ventilation state is an OBSERVED fact about
                # the plant, not a model prediction (see event-semantics rules).
                emit(event_type="utility_condition", zone_id=z.zone_id,
                     value={"ventilation_flow_ratio": z.ventilation_flow_ratio,
                            "ventilation_status": z.ventilation_status,
                            "observation_source": "operator_entered"},
                     offset=0, severity=1.0 - z.ventilation_flow_ratio, confidence=1.0,
                     info_class=InformationClass.MEASURED, source="scenario_state")

        for a in self.assets:
            if a.failure_probability > 0.0:
                # Operator-entered equipment condition is an OBSERVED fact.
                # A *predicted* failure probability only comes from the trained
                # AI4I model via machine_readings -> engine/model_events.py.
                emit(event_type="equipment_failure", zone_id=a.zone_id,
                     value={"failure_probability": a.failure_probability,
                            "failure_mode": a.condition,
                            "observation_source": "operator_entered"},
                     offset=0, severity=a.failure_probability, confidence=1.0,
                     info_class=InformationClass.MEASURED, source="scenario_state",
                     asset_id=a.asset_id)

        # NOTE: gas readings that carry a raw 128-dim `features` array are
        # deliberately NOT lowered here. Those must pass through the trained
        # gas model (see engine.model_events.gas_events_from_scenario); this
        # method only lowers operator-entered MEASURED values.
        for g in self.gas_readings:
            if g.features is not None:
                continue
            emit(event_type="gas_anomaly", zone_id=g.zone_id,
                 value={"gas_type": g.gas_type, "concentration_ppm": g.concentration_ppm,
                        "sensor_id": g.sensor_id},
                 offset=g.offset_seconds, severity=g.severity, confidence=g.confidence,
                 info_class=InformationClass.MEASURED, source="scenario_gas")

        # Explicit timeline events.
        for e in self.events:
            value = dict(e.value)
            if e.sensor_id and "sensor_id" not in value:
                value["sensor_id"] = e.sensor_id
            if e.permit_id and "permit_id" not in value:
                value["permit_id"] = e.permit_id
            emit(event_type=str(e.event_type), zone_id=e.zone_id, value=value,
                 offset=e.offset_seconds, severity=e.severity, confidence=e.confidence,
                 info_class=e.information_class, source=e.source,
                 worker_id=e.worker_id, asset_id=e.asset_id)

        events.sort(key=lambda ev: ev.event_time)
        return events
