"""Canonical data contracts for CAUSALCUT.

Every module in the system speaks in these types. The single most important
invariant here is the *information class* tag: measured observations, model
predictions, synthetic assumptions, counterfactual estimates, regulatory
evidence and human decisions are never silently mixed. The tag travels with
the data from ingestion all the way to the operator console.

Mirrors sections 2.3 and 5 of the CAUSALCUT design document.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class InformationClass(str, Enum):
    """The provenance/trust class of a piece of data (design doc 2.3)."""

    MEASURED = "M"          # directly from a sensor / camera
    PREDICTED = "P"         # output of a trained ML model
    SYNTHETIC = "S"         # generated assumption (e.g. synthetic permit)
    COUNTERFACTUAL = "C"    # "what-if" simulation estimate
    REGULATORY = "R"        # retrieved from OISD/DGMS/Factories Act corpus
    HUMAN = "H"             # operator approval / rejection / decision


class EventType(str, Enum):
    GAS_ANOMALY = "gas_anomaly"
    EQUIPMENT_FAILURE = "equipment_failure"
    PPE_VIOLATION = "ppe_violation"
    PERMIT_CONFLICT = "permit_conflict"
    PERMIT_STATUS = "permit_status"
    SHIFT_INCONSISTENCY = "shift_inconsistency"
    SHIFT_HANDOVER = "shift_handover"
    BARRIER_STATUS = "barrier_status"
    UTILITY_CONDITION = "utility_condition"
    WORKER_PRESENCE = "worker_presence"
    COMPOUND_RISK = "compound_risk"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class NodeType(str, Enum):
    ZONE = "zone"
    ASSET = "asset"
    WORKER = "worker"
    SENSOR = "sensor"
    PERMIT = "permit"
    BARRIER = "barrier"
    HAZARD = "hazard"


class SafetyEvent(BaseModel):
    """The canonical event every module emits and the hypergraph consumes.

    Corresponds to the Canonical Event Schema in design doc 5.1.
    """

    event_id: str = Field(default_factory=_new_id)
    factory_id: str = "steelforge-001"
    zone_id: Optional[str] = None
    event_type: EventType
    worker_id: Optional[str] = None
    asset_id: Optional[str] = None
    sensor_id: Optional[str] = None
    permit_id: Optional[str] = None

    event_time: datetime = Field(default_factory=_utcnow)
    # ISO-8601 duration string; how long this observation stays valid.
    validity_window: str = "PT5M"

    value: dict[str, Any] = Field(default_factory=dict)

    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)

    source: str = "unknown"
    model_version: Optional[str] = None
    provenance: Optional[str] = None

    information_class: InformationClass
    synthetic_flag: bool = False
    correlation_id: Optional[str] = None
    schema_version: str = "1.0.0"

    @field_validator("synthetic_flag", mode="after")
    @classmethod
    def _sync_synthetic_flag(cls, v: bool, info) -> bool:
        # A synthetic-class event is always flagged synthetic.
        ic = info.data.get("information_class")
        if ic == InformationClass.SYNTHETIC:
            return True
        return v

    def is_measured(self) -> bool:
        return self.information_class == InformationClass.MEASURED

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class HyperedgeCondition(BaseModel):
    """One predicate that must hold for a compound hyperedge to activate."""

    node: str
    predicate: str
    satisfied: bool = False
    info_class: InformationClass = InformationClass.PREDICTED
    observed_value: Optional[Any] = None


class Hyperedge(BaseModel):
    """A compound-danger relationship over >=2 nodes (design doc 5.3)."""

    hyperedge_id: str
    template_id: Optional[str] = None
    constituent_nodes: list[str]
    conditions: list[HyperedgeCondition] = Field(default_factory=list)
    pathway: str = ""
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    activation_time: Optional[datetime] = None
    activated: bool = False
    synthetic_flag: bool = False

    def dominant_info_class(self) -> InformationClass:
        """The weakest-trust class among satisfied conditions.

        If any condition is only predicted/counterfactual, the whole edge is
        no stronger than that. Measured beats predicted beats synthetic.
        """
        order = {
            InformationClass.MEASURED: 3,
            InformationClass.REGULATORY: 3,
            InformationClass.PREDICTED: 2,
            InformationClass.COUNTERFACTUAL: 1,
            InformationClass.SYNTHETIC: 1,
            InformationClass.HUMAN: 3,
        }
        satisfied = [c for c in self.conditions if c.satisfied]
        if not satisfied:
            return InformationClass.PREDICTED
        weakest = min(satisfied, key=lambda c: order.get(c.info_class, 2))
        return weakest.info_class


class ShiftHandover(BaseModel):
    """A shift changeover record used by the handover validator."""

    handover_id: str = Field(default_factory=_new_id)
    zone_id: str
    outgoing_shift: str
    incoming_shift: str
    outgoing_officer: str
    incoming_officer: Optional[str] = None
    handover_time: datetime = Field(default_factory=_utcnow)
    acknowledged: bool = False
    open_permits: list[str] = Field(default_factory=list)
    open_alarms: list[str] = Field(default_factory=list)
    notes: str = ""
    information_class: InformationClass = InformationClass.SYNTHETIC


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DEFER = "DEFER"


class HumanApproval(BaseModel):
    """Operator decision on a recommendation (design doc 5.7)."""

    approval_id: str = Field(default_factory=_new_id)
    recommendation_id: str
    approver_id: str
    approver_role: str
    decision: ApprovalDecision
    reason: str = ""
    timestamp: datetime = Field(default_factory=_utcnow)
    information_class: InformationClass = InformationClass.HUMAN
