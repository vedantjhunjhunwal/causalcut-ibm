import json
import pytest
import numpy as np
from pathlib import Path
from pydantic import ValidationError
from app.schemas.scenario import Scenario
from app.engine.scenario_runner import run_scenario

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Test 01: Coke Oven Flash-Fire (Design Doc §8)
# --------------------------------------------------------------------------- #
def test_01_coke_oven_flashfire():
    sc_data = json.loads((ROOT / "scenarios" / "coke_oven_scenario.json").read_text())
    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    # Flash-fire pathway HE-042 fires
    paths = res["causal_paths"]
    assert len(paths) >= 1
    pathways = [p["pathway"] for p in paths]
    assert "toxic_exposure_or_flash_fire" in pathways or "acute_toxic_exposure" in pathways
    rec = res["recommendation"]
    assert rec is not None
    assert len(rec["interventions"]) >= 1
    assert res["zone_risk"]["zone-1"] >= 0.70


# --------------------------------------------------------------------------- #
# Test 02: Validation & Fail-Closed Behavior
# --------------------------------------------------------------------------- #
def test_02_invalid_permit_fails_closed():
    sc_data = json.loads((ROOT / "scenarios" / "coke_oven_scenario.json").read_text())
    sc_data["permits"][0]["status"] = "INVALID_UNRECOGNIZED_STATUS"

    with pytest.raises(ValidationError) as excinfo:
        Scenario.model_validate(sc_data)

    assert "status" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Test 03: Extreme Methane with String Sensor Identifiers
# --------------------------------------------------------------------------- #
def test_03_extreme_methane_with_string_sensor_ids():
    sc_data = {
        "scenario_id": "test-03_extreme_methane",
        "name": "Extreme Methane Hazard",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {
                "zone_id": "zone-boiler-house",
                "name": "Boiler House",
                "hazard_class": "gas_hazard",
                "baseline_gas_threshold_ppm": 200.0,
                "ventilation_status": "nominal",
                "ventilation_flow_ratio": 1.0,
            },
            {
                "zone_id": "zone-feedwater-gallery",
                "name": "Feedwater Gallery",
                "hazard_class": "normal",
            },
            {
                "zone_id": "zone-control-west",
                "name": "Control West",
                "hazard_class": "admin",
            },
        ],
        "zone_adjacency": [
            {"zone_a": "zone-boiler-house", "zone_b": "zone-feedwater-gallery", "medium": "doorway"},
            {"zone_a": "zone-feedwater-gallery", "zone_b": "zone-control-west", "medium": "doorway"},
        ],
        "sensors": [
            {"sensor_id": "GS-MET-12", "zone_id": "zone-boiler-house", "modality": "gas", "unit": "ppm"},
            {"sensor_id": "HYD-FG-03", "zone_id": "zone-feedwater-gallery", "modality": "hydraulic"},
            {"sensor_id": "VIB-B12", "zone_id": "zone-boiler-house", "modality": "vibration"},
        ],
        "assets": [
            {"asset_id": "PUMP-BF-12", "zone_id": "zone-boiler-house", "asset_type": "pump"}
        ],
        "workers": [
            {"worker_id": "W-B31", "zone_id": "zone-boiler-house", "present": True, "missing_ppe": []},
            {"worker_id": "W-B36", "zone_id": "zone-feedwater-gallery", "present": True, "missing_ppe": []},
        ],
        "permits": [],
        "gas_readings": [
            {
                "sensor_id": "GS-MET-12",
                "zone_id": "zone-boiler-house",
                "gas_type": "methane",
                "concentration_ppm": 850.0,
                "features": list(np.random.RandomState(42).randn(128) * 50.0),
                "severity": 0.95,
                "offset_seconds": 10,
            }
        ],
        "events": [],
    }

    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    assert res["scenario_id"] == "test-03_extreme_methane"
    node_ids = {n["id"] for n in res["graph"]["nodes"]}
    assert "GS-MET-12" in node_ids
    assert "HYD-FG-03" in node_ids
    assert "VIB-B12" in node_ids

    paths = res["causal_paths"]
    assert len(paths) >= 1
    pathways = [p["pathway"] for p in paths]
    assert "acute_toxic_exposure" in pathways or "gas_accumulation" in pathways

    rec = res["recommendation"]
    assert rec is not None
    actions = " ".join(iv["action"] for iv in rec["interventions"]).lower()
    assert "gas isolation valve" in actions


# --------------------------------------------------------------------------- #
# Test 04: Gas Near Threshold (Below Alarm Limit)
# --------------------------------------------------------------------------- #
def test_04_gas_near_threshold():
    sc_data = {
        "scenario_id": "test-04_gas_near_threshold",
        "name": "Gas Near Threshold",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {
                "zone_id": "zone-boiler-house",
                "name": "Boiler House",
                "baseline_gas_threshold_ppm": 200.0,
                "ventilation_status": "nominal",
                "ventilation_flow_ratio": 1.0,
            }
        ],
        "sensors": [
            {"sensor_id": "GS-01", "zone_id": "zone-boiler-house", "modality": "gas", "unit": "ppm"}
        ],
        "workers": [
            {"worker_id": "W-01", "zone_id": "zone-boiler-house", "present": True, "missing_ppe": []}
        ],
        "gas_readings": [
            {
                "sensor_id": "GS-01",
                "zone_id": "zone-boiler-house",
                "gas_type": "methane",
                "concentration_ppm": 180.0,  # Below 200 ppm threshold
                "severity": 0.35,
                "offset_seconds": 0,
            }
        ],
        "permits": [],
        "assets": [],
        "events": [],
    }

    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    # Gas is below threshold, so no compound pathway should be active
    assert len(res["causal_paths"]) == 0
    assert res["recommendation"] is None
    # Zone risk should be below critical (warning range ~0.36, not 1.0)
    assert res["zone_risk"]["zone-boiler-house"] < 0.50


# --------------------------------------------------------------------------- #
# Test 05: Machine Failure Extreme (AI4I Catastrophic Failure)
# --------------------------------------------------------------------------- #
def test_05_machine_failure_extreme():
    sc_data = {
        "scenario_id": "test-05_machine_failure_extreme",
        "name": "Extreme Machine Failure",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {
                "zone_id": "zone-machine-shop",
                "name": "Machine Shop",
                "hazard_class": "rotating_equipment",
            }
        ],
        "assets": [
            {
                "asset_id": "VENT-BH-04",
                "zone_id": "zone-machine-shop",
                "asset_type": "ventilation_fan",
                "failure_probability": 0.45,
                "condition": "vibration_nominal",
            },
            {
                "asset_id": "PUMP-BF-12",
                "zone_id": "zone-machine-shop",
                "asset_type": "pump",
                "failure_probability": 0.99,
                "condition": "bearing_overheat_pressure_fluctuation_severe",
            },
        ],
        "workers": [
            {"worker_id": "W-01", "zone_id": "zone-machine-shop", "present": True, "missing_ppe": []}
        ],
        "gas_readings": [],
        "permits": [],
        "events": [],
    }

    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    # Machine failure pathway should fire
    paths = res["causal_paths"]
    assert len(paths) >= 1
    pathways = [p["pathway"] for p in paths]
    assert "mechanical_injury" in pathways or "equipment_hazard" in pathways

    # Zone risk reflects machine failure severity
    assert res["zone_risk"]["zone-machine-shop"] >= 0.65

    # Recommendation isolates the worst failing equipment (PUMP-BF-12, NOT VENT-BH-04)
    rec = res["recommendation"]
    assert rec is not None
    actions = " ".join(iv["action"] for iv in rec["interventions"])
    assert "PUMP-BF-12" in actions
    assert "VENT-BH-04" not in actions


# --------------------------------------------------------------------------- #
# Test 06: Ventilation Failure
# --------------------------------------------------------------------------- #
def test_06_ventilation_failure():
    sc_data = {
        "scenario_id": "test-06_ventilation_failure",
        "name": "Critical Ventilation Failure",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {
                "zone_id": "zone-coke-oven",
                "name": "Coke Oven",
                "ventilation_status": "failed",
                "ventilation_flow_ratio": 0.20,
            }
        ],
        "workers": [
            {"worker_id": "W-01", "zone_id": "zone-coke-oven", "present": True, "missing_ppe": []}
        ],
        "gas_readings": [],
        "permits": [],
        "assets": [],
        "events": [],
    }

    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    # Ventilation starvation pathway should fire
    paths = res["causal_paths"]
    assert len(paths) >= 1
    assert any(p["pathway"] == "ventilation_starvation" for p in paths)

    # Recommendation should override ventilation
    rec = res["recommendation"]
    assert rec is not None
    actions = " ".join(iv["action"] for iv in rec["interventions"]).lower()
    assert "ventilation" in actions


# --------------------------------------------------------------------------- #
# Test 07: Fully Compliant Workers (No PPE Violations)
# --------------------------------------------------------------------------- #
def test_07_worker_ppe_compliant():
    sc_data = {
        "scenario_id": "test-07_worker_ppe_compliant",
        "name": "Worker Fully Compliant",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {
                "zone_id": "zone-1",
                "name": "Boiler House",
                "baseline_gas_threshold_ppm": 200.0,
            }
        ],
        "sensors": [
            {"sensor_id": "GS-01", "zone_id": "zone-1", "modality": "gas", "unit": "ppm"}
        ],
        "workers": [
            {"worker_id": "W-B31", "zone_id": "zone-1", "present": True, "missing_ppe": []},
            {"worker_id": "W-B36", "zone_id": "zone-1", "present": True, "missing_ppe": []},
            {"worker_id": "W-001", "zone_id": "zone-1", "present": True, "missing_ppe": []},
            {"worker_id": "W-002", "zone_id": "zone-1", "present": True, "missing_ppe": []},
        ],
        "gas_readings": [
            {
                "sensor_id": "GS-01",
                "zone_id": "zone-1",
                "gas_type": "methane",
                "concentration_ppm": 600.0,
                "severity": 0.85,
                "offset_seconds": 0,
            }
        ],
        "permits": [],
        "assets": [],
        "events": [],
    }

    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    # Causal path factors should NOT contain unprotected_worker
    for p in res["causal_paths"]:
        assert "unprotected_worker" not in p["contributing_factors"]

    # Recommended cut should target gas isolation, NOT PPE enforcement
    rec = res["recommendation"]
    assert rec is not None
    for iv in rec["interventions"]:
        assert "unprotected_worker" not in iv["breaks_factors"]
        assert iv["intervention_type"] != "enforce_ppe"
    actions = " ".join(iv["action"] for iv in rec["interventions"]).lower()
    assert "gas isolation valve" in actions


# --------------------------------------------------------------------------- #
# Test 08: Multiple Worker PPE Violations
# --------------------------------------------------------------------------- #
def test_08_multiple_worker_violations():
    sc_data = {
        "scenario_id": "test-08_multiple_worker_violations",
        "name": "Multiple Worker Violations",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {
                "zone_id": "zone-1",
                "name": "Boiler House",
                "baseline_gas_threshold_ppm": 200.0,
            }
        ],
        "workers": [
            {"worker_id": "W-01", "zone_id": "zone-1", "present": True, "missing_ppe": ["hard_hat", "gloves"]},
            {"worker_id": "W-02", "zone_id": "zone-1", "present": True, "missing_ppe": ["goggles", "safety_vest"]},
        ],
        "gas_readings": [],
        "permits": [],
        "assets": [],
        "events": [],
    }

    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    # Graph reflects PPE violations
    graph = res["graph"]
    worker_nodes = [n for n in graph["nodes"] if n["type"] == "worker"]
    assert len(worker_nodes) == 2
    assert all(w["status"] == "warning" for w in worker_nodes)

    # If causal path has unprotected worker, recommendation enforces PPE specifically naming violators
    if res["recommendation"]:
        ppe_ivs = [iv for iv in res["recommendation"]["interventions"] if iv["intervention_type"] == "enforce_ppe"]
        if ppe_ivs:
            action_text = ppe_ivs[0]["action"]
            assert "W-01" in action_text or "W-02" in action_text


# --------------------------------------------------------------------------- #
# Test 09: No Workers Present (Unmanned Facility)
# --------------------------------------------------------------------------- #
def test_09_no_workers():
    sc_data = {
        "scenario_id": "test-09_no_workers",
        "name": "Unmanned Facility Gas Leak",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {
                "zone_id": "zone-boiler-house",
                "name": "Boiler House",
                "baseline_gas_threshold_ppm": 200.0,
            }
        ],
        "sensors": [
            {"sensor_id": "GS-01", "zone_id": "zone-boiler-house", "modality": "gas", "unit": "ppm"}
        ],
        "workers": [],  # ZERO workers
        "gas_readings": [
            {
                "sensor_id": "GS-01",
                "zone_id": "zone-boiler-house",
                "gas_type": "methane",
                "concentration_ppm": 750.0,
                "severity": 0.90,
                "offset_seconds": 0,
            }
        ],
        "permits": [],
        "assets": [],
        "events": [],
    }

    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    # 1. Graph must have ZERO worker nodes
    worker_nodes = [n for n in res["graph"]["nodes"] if n["type"] == "worker"]
    assert len(worker_nodes) == 0

    # 2. Gas accumulation pathway is active (atmospheric containment loss)
    paths = res["causal_paths"]
    assert len(paths) >= 1
    assert any(p["pathway"] == "gas_accumulation" for p in paths)

    # 3. Acute toxic worker exposure must NOT activate (no workers present)
    assert not any(p["pathway"] == "acute_toxic_exposure" for p in paths)

    # 4. Recommendation is gas isolation, NEVER worker evacuation
    rec = res["recommendation"]
    assert rec is not None
    for iv in rec["interventions"]:
        assert iv["intervention_type"] != "evacuate_worker"
        assert "worker" not in iv["action"].lower()
    actions = " ".join(iv["action"] for iv in rec["interventions"]).lower()
    assert "gas isolation valve" in actions


# --------------------------------------------------------------------------- #
# Test 10: Multi-Zone Cascading Diffusion
# --------------------------------------------------------------------------- #
def test_10_multi_zone_cascading():
    sc_data = {
        "scenario_id": "test-10_cascading_diffusion",
        "name": "Multi-Zone Cascading Gas Leak",
        "factory_id": "steelforge-001",
        "safety_threshold": 0.15,
        "zones": [
            {"zone_id": "zone-1", "name": "Coke Oven", "baseline_gas_threshold_ppm": 200.0},
            {"zone_id": "zone-4", "name": "Shared Duct", "hazard_class": "propagation"},
            {"zone_id": "zone-2", "name": "Blast Furnace", "hazard_class": "standard"},
        ],
        "zone_adjacency": [
            {"zone_a": "zone-1", "zone_b": "zone-4", "medium": "ventilation_duct"},
            {"zone_a": "zone-4", "zone_b": "zone-2", "medium": "shared_duct"},
        ],
        "sensors": [
            {"sensor_id": "GS-01", "zone_id": "zone-1", "modality": "gas", "unit": "ppm"}
        ],
        "workers": [
            {"worker_id": "W-01", "zone_id": "zone-1", "present": True, "missing_ppe": []},
            {"worker_id": "W-02", "zone_id": "zone-2", "present": True, "missing_ppe": []},
        ],
        "gas_readings": [
            {
                "sensor_id": "GS-01",
                "zone_id": "zone-1",
                "gas_type": "methane",
                "concentration_ppm": 700.0,
                "severity": 0.88,
                "offset_seconds": 0,
            }
        ],
        "permits": [],
        "assets": [],
        "events": [],
    }

    sc = Scenario.model_validate(sc_data)
    res = run_scenario(sc)

    # Risk propagates to adjacent propagation zones
    assert res["zone_risk"]["zone-1"] >= 0.70
    paths = res["causal_paths"]
    assert len(paths) >= 1
    assert any(len(p.get("propagation_zones", [])) > 0 for p in paths)
