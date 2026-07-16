"""Canonical Safety Event — the one schema every module speaks.

Design doc §5.1. Every producer (gas anomaly, equipment failure, PPE detection,
permit validation, shift handover) normalises to this shape before anything
downstream — hypergraph, risk propagation, optimiser — is allowed to see it.

Invariants enforced here (not downstream):
  * information_class and synthetic_flag can never contradict each other
  * a [P] prediction must name the model that produced it
  * severity / confidence / uncertainty are bounded [0, 1]
  * event_time must be sane relative to ingest time
  * payload_hash gives content-level dedup on top of event_id
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.schemas.enums import EventType, InformationClass, ZoneId

SCHEMA_VERSION = "1.0.0"

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SafetyEvent(BaseModel):
    """Immutable, append-only record of one observation/prediction/assumption."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "event_id": "3f2b0c9a-9b3e-4a10-9a0e-4f2f1f9a1b21",
                    "factory_id": "steelforge-001",
                    "zone_id": "zone-1",
                    "event_type": "gas_anomaly",
                    "worker_id": None,
                    "asset_id": None,
                    "event_time": "2026-07-11T10:30:00Z",
                    "validity_window": "PT5M",
                    "value": {"gas_type": "ammonia", "concentration_ppm": 215.4,
                              "sensor_id": "GS-03"},
                    "severity": 0.82,
                    "confidence": 0.91,
                    "uncertainty": 0.15,
                    "source": "gas_anomaly_module_v2",
                    "model_version": "xgb-gas-v2.1.0",
                    "provenance": "UCI_GasSensorDrift_Batch7",
                    "information_class": "M",
                    "synthetic_flag": False,
                    "schema_version": "1.0.0",
                }
            ]
        },
    )

    # --- Identity -------------------------------------------------------
    event_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Idempotency key. Re-ingesting the same event_id is a no-op.",
    )
    factory_id: str = Field(default="steelforge-001", min_length=1, max_length=64)
    zone_id: ZoneId
    event_type: EventType

    # --- Subject --------------------------------------------------------
    worker_id: str | None = Field(default=None, max_length=32, examples=["W-003"])
    asset_id: str | None = Field(default=None, max_length=32, examples=["LATHE-01"])

    # --- Time -----------------------------------------------------------
    event_time: datetime = Field(
        description="When the observation happened at the plant (UTC)."
    )
    validity_window: timedelta = Field(
        default=timedelta(minutes=5),
        description="ISO-8601 duration. After event_time + this, the event is stale.",
    )

    # --- Payload --------------------------------------------------------
    value: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-type-specific body, e.g. {'gas_type': 'ammonia', "
        "'concentration_ppm': 215.4}.",
    )

    # --- Scoring --------------------------------------------------------
    severity: UnitInterval = 0.0
    confidence: UnitInterval = 1.0
    uncertainty: UnitInterval = 0.0

    # --- Provenance -----------------------------------------------------
    source: str = Field(min_length=1, max_length=128, examples=["gas_anomaly_module_v2"])
    model_version: str | None = Field(default=None, max_length=64)
    provenance: str | None = Field(
        default=None, max_length=256,
        description="Upstream dataset / batch identifier for audit.",
    )

    # --- Classification (the whole point) -------------------------------
    information_class: InformationClass
    synthetic_flag: bool = False

    # --- Envelope -------------------------------------------------------
    schema_version: str = SCHEMA_VERSION
    correlation_id: str | None = Field(
        default=None,
        description="Trace id linking this event to the request that carried it.",
    )
    ingest_time: datetime = Field(default_factory=_utcnow)

    # ---------------------------------------------------------------- #
    # Validators
    # ---------------------------------------------------------------- #
    @field_validator("event_time", "ingest_time")
    @classmethod
    def _require_tz_aware_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (use trailing 'Z')")
        return v.astimezone(timezone.utc)

    @field_validator("validity_window")
    @classmethod
    def _positive_window(cls, v: timedelta) -> timedelta:
        if v <= timedelta(0):
            raise ValueError("validity_window must be positive")
        if v > timedelta(hours=24):
            raise ValueError("validity_window must not exceed 24h")
        return v

    @field_validator("worker_id")
    @classmethod
    def _worker_format(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("W-"):
            raise ValueError("worker_id must look like 'W-003'")
        return v

    @model_validator(mode="after")
    def _class_consistency(self) -> Self:
        ic, synthetic = self.information_class, self.synthetic_flag

        if ic is InformationClass.SYNTHETIC and not synthetic:
            raise ValueError("information_class 'S' requires synthetic_flag=true")
        if ic is InformationClass.MEASURED and synthetic:
            raise ValueError(
                "information_class 'M' cannot be synthetic — a measurement is "
                "either from the plant or it is not measured"
            )
        if ic is InformationClass.PREDICTED and not self.model_version:
            raise ValueError("information_class 'P' requires model_version")
        if ic is InformationClass.COUNTERFACTUAL and self.uncertainty == 0.0:
            raise ValueError(
                "information_class 'C' must carry non-zero uncertainty — a "
                "counterfactual is never certain"
            )
        return self

    @model_validator(mode="after")
    def _subject_present_when_required(self) -> Self:
        if self.event_type in {EventType.PPE_VIOLATION, EventType.WORKER_PRESENCE} \
                and self.worker_id is None:
            raise ValueError(f"{self.event_type} requires worker_id")
        if self.event_type is EventType.EQUIPMENT_FAILURE and self.asset_id is None:
            raise ValueError("equipment_failure requires asset_id")
        return self

    # ---------------------------------------------------------------- #
    # Serialisation
    # ---------------------------------------------------------------- #
    @field_serializer("event_time", "ingest_time")
    def _ser_dt(self, v: datetime) -> str:
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    # ---------------------------------------------------------------- #
    # Behaviour
    # ---------------------------------------------------------------- #
    @property
    def expires_at(self) -> datetime:
        return self.event_time + self.validity_window

    def is_stale(self, now: datetime | None = None) -> bool:
        return (now or _utcnow()) > self.expires_at

    def payload_hash(self) -> str:
        """Content fingerprint — catches the same reading re-sent under a new
        event_id (a real failure mode with at-least-once sensor gateways)."""
        material = {
            "factory_id": self.factory_id,
            "zone_id": str(self.zone_id),
            "event_type": str(self.event_type),
            "worker_id": self.worker_id,
            "asset_id": self.asset_id,
            "event_time": self.event_time.isoformat(),
            "value": self.value,
            "source": self.source,
        }
        blob = json.dumps(material, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


class SafetyEventIn(BaseModel):
    """Inbound shape. Everything the platform owns (ingest_time, correlation_id,
    schema_version) is deliberately absent — producers do not get to set it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_id: uuid.UUID | None = None
    factory_id: str = "steelforge-001"
    zone_id: ZoneId
    event_type: EventType
    worker_id: str | None = None
    asset_id: str | None = None
    event_time: datetime
    validity_window: timedelta | None = None
    value: dict[str, Any] = Field(default_factory=dict)
    severity: UnitInterval = 0.0
    confidence: UnitInterval = 1.0
    uncertainty: UnitInterval = 0.0
    source: str
    model_version: str | None = None
    provenance: str | None = None
    information_class: InformationClass
    synthetic_flag: bool = False

    def to_canonical(
        self, correlation_id: str | None, default_window: timedelta
    ) -> SafetyEvent:
        data = self.model_dump(exclude_none=False)
        data["event_id"] = self.event_id or uuid.uuid4()
        data["validity_window"] = self.validity_window or default_window
        data["correlation_id"] = correlation_id
        data["schema_version"] = SCHEMA_VERSION
        data["ingest_time"] = _utcnow()
        return SafetyEvent.model_validate(data)
