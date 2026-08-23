"""Bow-Tie formalism layer for CAUSALCUT — G1 of the Gap Analysis.

Every CompoundRule encodes a bow-tie diagram in process-safety terminology:
  threats (causal preconditions) -> [preventive barriers] -> TOP EVENT
                                 -> [mitigative barriers] -> consequences

This module provides the Pydantic models and a registry that builds a BowTie
object from each CompoundRule so the API and dashboard can expose the
recognized industry formalism, making the existing detection logic legible to
process-safety engineers, DGMS/OISD auditors, and evaluation judges.

Design constraint: this is a READ-ONLY view layer over CompoundRule.
No rule evaluation logic lives here -- all detection continues through
CompoundRuleEngine unmodified.
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field

from app.engine.types import InformationClass


# --------------------------------------------------------------------------- #
# Bow-Tie data models
# --------------------------------------------------------------------------- #

class ThreatNode(BaseModel):
    """A causal precondition that can trigger the top event."""
    threat_id: str
    description: str
    info_class: InformationClass = InformationClass.MEASURED


class ConsequenceNode(BaseModel):
    """A potential harm outcome if the top event is not contained."""
    consequence_id: str
    description: str
    severity_category: Literal["minor", "moderate", "severe", "catastrophic"] = "severe"


class BowTie(BaseModel):
    """Bow-tie diagram definition for one hazard scenario.

    Maps directly to a CompoundRule but uses the formal process-safety
    vocabulary: threats -> preventive barriers -> top event ->
    mitigative barriers -> consequences.

    source_reference traces each bow-tie back to the HAZOP worksheet,
    OISD clause, or historical incident that justifies this rule -- the
    field that provides audit traceability required by DGMS/OISD frameworks.
    """
    hazard_id: str = Field(description="Unique bow-tie identifier, matches template_id")
    top_event: str = Field(description="Loss-of-control event at the centre of the bow-tie")
    source_reference: str = Field(
        description="HAZOP worksheet / OISD clause / historical incident ID"
    )
    threats: list[ThreatNode]
    preventive_barriers: list[str] = Field(
        description="Intervention types that stop threat -> top event transition"
    )
    mitigative_barriers: list[str] = Field(
        description="Intervention types that limit consequences after top event"
    )
    consequences: list[ConsequenceNode]
    pathway: str = Field(description="Internal pathway tag (maps to AccidentPath.pathway)")


# --------------------------------------------------------------------------- #
# Static bow-tie metadata per rule
# (preventive/mitigative classification and consequences)
# --------------------------------------------------------------------------- #

_BOWTIE_METADATA: dict[str, dict] = {
    "HE-042": {
        "threats": [
            ThreatNode(threat_id="T-GAS-001", description="Rising CO/H2 concentration above LEL threshold"),
            ThreatNode(threat_id="T-PERMIT-001", description="Active hot-work permit in gas-affected zone",
                       info_class=InformationClass.SYNTHETIC),
            ThreatNode(threat_id="T-PPE-001", description="Worker present without required PPE",
                       info_class=InformationClass.MEASURED),
            ThreatNode(threat_id="T-VENT-001", description="Ventilation flow < 60% nominal",
                       info_class=InformationClass.PREDICTED),
        ],
        "preventive_barriers": ["suspend_permit", "gas_isolation", "increase_ventilation"],
        "mitigative_barriers": ["evacuate_worker", "enforce_ppe", "close_zone"],
        "consequences": [
            ConsequenceNode(consequence_id="C-FIRE-001",
                            description="Flash fire / explosion in occupied zone",
                            severity_category="catastrophic"),
            ConsequenceNode(consequence_id="C-TOX-001",
                            description="Acute CO/H2 toxic inhalation injury",
                            severity_category="severe"),
        ],
    },
    "HE-TOXIC-EXPOSURE": {
        "threats": [
            ThreatNode(threat_id="T-GAS-002",
                       description="Gas concentration above TLV-STEL with worker present"),
            ThreatNode(threat_id="T-VENT-002", description="Ventilation flow < 70% nominal",
                       info_class=InformationClass.PREDICTED),
        ],
        "preventive_barriers": ["gas_isolation", "increase_ventilation"],
        "mitigative_barriers": ["evacuate_worker", "enforce_ppe"],
        "consequences": [
            ConsequenceNode(consequence_id="C-TOX-002",
                            description="Toxic inhalation / asphyxiation",
                            severity_category="severe"),
        ],
    },
    "HE-GAS-ACCUMULATION": {
        "threats": [
            ThreatNode(threat_id="T-GAS-003",
                       description="Gas concentration rising, no workers yet present"),
            ThreatNode(threat_id="T-VENT-003",
                       description="Ventilation degraded, accumulation continuing",
                       info_class=InformationClass.PREDICTED),
        ],
        "preventive_barriers": ["gas_isolation", "increase_ventilation"],
        "mitigative_barriers": ["close_zone"],
        "consequences": [
            ConsequenceNode(consequence_id="C-GAS-001",
                            description="Explosive atmosphere / asphyxiation hazard",
                            severity_category="moderate"),
        ],
    },
    "HE-IGNITION-UNGUARDED": {
        "threats": [
            ThreatNode(threat_id="T-PERMIT-002", description="Hot-work permit active",
                       info_class=InformationClass.SYNTHETIC),
            ThreatNode(threat_id="T-BARRIER-001", description="Fire suppression barrier offline"),
            ThreatNode(threat_id="T-GAS-004",
                       description="Gas present, creating ignitable mixture"),
        ],
        "preventive_barriers": ["suspend_permit", "gas_isolation"],
        "mitigative_barriers": ["close_zone"],
        "consequences": [
            ConsequenceNode(consequence_id="C-FIRE-002",
                            description="Uncontrolled ignition / fire with suppression gap",
                            severity_category="catastrophic"),
        ],
    },
    "HE-MECH-EXPOSURE": {
        "threats": [
            ThreatNode(threat_id="T-EQUIP-001",
                       description="Rotating equipment failure probability > 50%",
                       info_class=InformationClass.PREDICTED),
            ThreatNode(threat_id="T-WORKER-001",
                       description="Worker present in equipment hazard zone"),
        ],
        "preventive_barriers": ["isolate_equipment"],
        "mitigative_barriers": ["evacuate_worker", "close_zone"],
        "consequences": [
            ConsequenceNode(consequence_id="C-MECH-001",
                            description="Mechanical contact injury to worker",
                            severity_category="severe"),
        ],
    },
    "HE-EQUIPMENT-FAILURE": {
        "threats": [
            ThreatNode(threat_id="T-EQUIP-002",
                       description="Critical asset failure probability exceeding threshold",
                       info_class=InformationClass.PREDICTED),
        ],
        "preventive_barriers": ["isolate_equipment"],
        "mitigative_barriers": ["close_zone"],
        "consequences": [
            ConsequenceNode(consequence_id="C-EQUIP-001",
                            description="Equipment failure / production loss / secondary hazard",
                            severity_category="moderate"),
        ],
    },
    "HE-VENTILATION-FAILURE": {
        "threats": [
            ThreatNode(threat_id="T-VENT-004",
                       description="Ventilation flow < 40% nominal -- critical deficit",
                       info_class=InformationClass.MEASURED),
            ThreatNode(threat_id="T-WORKER-002",
                       description="Worker present in ventilation-starved zone"),
        ],
        "preventive_barriers": ["increase_ventilation"],
        "mitigative_barriers": ["evacuate_worker", "close_zone"],
        "consequences": [
            ConsequenceNode(consequence_id="C-VENT-001",
                            description="Asphyxiation in occupied zone",
                            severity_category="severe"),
        ],
    },
    "HE-VENTILATION-DEFICIT": {
        "threats": [
            ThreatNode(threat_id="T-VENT-005",
                       description="Severe zone ventilation airflow deficit",
                       info_class=InformationClass.MEASURED),
        ],
        "preventive_barriers": ["increase_ventilation"],
        "mitigative_barriers": ["close_zone"],
        "consequences": [
            ConsequenceNode(consequence_id="C-VENT-002",
                            description="Zone atmosphere degradation; gas accumulation risk",
                            severity_category="moderate"),
        ],
    },
}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

class BowTieRegistry:
    """Builds BowTie objects from CompoundRules and caches them.

    Call build_from_rules() once at startup after CompoundRuleEngine is
    initialised. The registry is then available to API routes via
    app.state.bowtie_registry.
    """

    def __init__(self) -> None:
        self._registry: dict[str, BowTie] = {}

    def build_from_rules(self, rules: list) -> None:
        """Populate the registry from the live CompoundRule list."""
        self._registry.clear()
        for rule in rules:
            meta = _BOWTIE_METADATA.get(rule.template_id, {})
            bt = BowTie(
                hazard_id=rule.template_id,
                top_event=rule.top_event or rule.name,
                source_reference=rule.source_reference,
                pathway=rule.pathway,
                threats=meta.get("threats", [
                    ThreatNode(
                        threat_id=f"T-{rule.template_id}-AUTO",
                        description=f"Compound precondition for {rule.name}",
                    )
                ]),
                preventive_barriers=meta.get("preventive_barriers", []),
                mitigative_barriers=meta.get("mitigative_barriers", ["close_zone"]),
                consequences=meta.get("consequences", [
                    ConsequenceNode(
                        consequence_id=f"C-{rule.template_id}-AUTO",
                        description=f"Outcome of: {rule.top_event or rule.name}",
                    )
                ]),
            )
            self._registry[rule.template_id] = bt

    def get(self, template_id: str) -> Optional[BowTie]:
        return self._registry.get(template_id)

    def list_all(self) -> list[BowTie]:
        return list(self._registry.values())

    def __len__(self) -> int:
        return len(self._registry)
