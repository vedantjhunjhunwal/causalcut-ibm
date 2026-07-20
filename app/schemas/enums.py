"""Controlled vocabularies for CAUSALCUT.

The InformationClass enum is the backbone of the design's central promise:
strict separation between measured observation, model prediction, synthetic
assumption, counterfactual estimate, regulatory evidence and human decision
(design doc §1.2, §2.3). Nothing enters the system untagged.
"""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return str(self.value)


class InformationClass(StrEnum):
    MEASURED = "M"          # directly from sensor / camera
    PREDICTED = "P"         # output of a trained model
    SYNTHETIC = "S"         # generated identity / permit / shift log
    COUNTERFACTUAL = "C"    # "what-if" simulation output
    REGULATORY = "R"        # RAG over OISD / DGMS / Factories Act
    HUMAN = "H"             # operator approval or rejection


class EventType(StrEnum):
    GAS_ANOMALY = "gas_anomaly"
    EQUIPMENT_FAILURE = "equipment_failure"
    PPE_VIOLATION = "ppe_violation"
    WORKER_PRESENCE = "worker_presence"
    PERMIT_CONFLICT = "permit_conflict"
    PERMIT_STATUS = "permit_status"
    SHIFT_INCONSISTENCY = "shift_inconsistency"
    BARRIER_STATUS = "barrier_status"
    UTILITY_CONDITION = "utility_condition"
    SENSOR_DRIFT = "sensor_drift"
    COMPOUND_RISK = "compound_risk"


class ZoneId(StrEnum):
    ZONE_1_COKE_OVEN = "zone-1"
    ZONE_2_BLAST_FURNACE = "zone-2"
    ZONE_3_MACHINE_SHOP = "zone-3"
    ZONE_4_SHARED_UTILITIES = "zone-4"
    ZONE_5_CCTV_CHECKPOINTS = "zone-5"
    ZONE_6_CONTROL_ROOM = "zone-6"


class GasType(StrEnum):
    ETHANOL = "ethanol"
    ETHYLENE = "ethylene"
    AMMONIA = "ammonia"
    ACETALDEHYDE = "acetaldehyde"
    ACETONE = "acetone"
    TOLUENE = "toluene"
    CARBON_MONOXIDE = "carbon_monoxide"
    METHANE = "methane"


class PermitType(StrEnum):
    HOT_WORK = "hot_work"
    CONFINED_SPACE = "confined_space"
    ELECTRICAL_ISOLATION = "electrical_isolation"
    MECHANICAL = "mechanical"
    LOTO = "loto"
    WORKING_AT_HEIGHT = "working_at_height"


class PermitStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    EXPIRED = "expired"


class BarrierStatus(StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class PPEItem(StrEnum):
    HARD_HAT = "hard_hat"
    SAFETY_VEST = "safety_vest"
    SAFETY_GOGGLES = "safety_goggles"
    GLOVES = "gloves"


class ProcessingStatus(StrEnum):
    ACCEPTED = "accepted"        # validated, queued
    DUPLICATE = "duplicate"      # event_id already seen -> idempotent no-op
    REJECTED = "rejected"        # failed validation
    QUEUE_FULL = "queue_full"    # backpressure; persisted but not queued
