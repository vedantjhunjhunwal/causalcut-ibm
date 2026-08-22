import json
import uuid

# Define the new zones and sensors based on the map
zones = [
    {
        "zone_id": "zone-cnc",
        "name": "CNC Machining Floor",
        "hazard_class": "standard",
        "baseline_gas_threshold_ppm": 100.0,
        "ventilation_status": "nominal",
        "ventilation_flow_ratio": 1.0
    },
    {
        "zone_id": "zone-hydraulic",
        "name": "Hydraulic Press Bay",
        "hazard_class": "standard",
        "baseline_gas_threshold_ppm": 100.0,
        "ventilation_status": "nominal",
        "ventilation_flow_ratio": 1.0
    },
    {
        "zone_id": "zone-gas",
        "name": "Gas Storage/Chemical Zone",
        "hazard_class": "gas_hazard",
        "baseline_gas_threshold_ppm": 150.0,
        "ventilation_status": "nominal",
        "ventilation_flow_ratio": 1.0
    },
    {
        "zone_id": "zone-ppe",
        "name": "PPE Checkpoint",
        "hazard_class": "standard",
        "baseline_gas_threshold_ppm": 100.0,
        "ventilation_status": "nominal",
        "ventilation_flow_ratio": 1.0
    },
    {
        "zone_id": "zone-control",
        "name": "Control Room",
        "hazard_class": "standard",
        "baseline_gas_threshold_ppm": 100.0,
        "ventilation_status": "nominal",
        "ventilation_flow_ratio": 1.0
    },
    {
        "zone_id": "zone-entrance",
        "name": "Main Entrance/Exit",
        "hazard_class": "standard",
        "baseline_gas_threshold_ppm": 100.0,
        "ventilation_status": "nominal",
        "ventilation_flow_ratio": 1.0
    },
    {
        "zone_id": "zone-break",
        "name": "Break Room",
        "hazard_class": "standard",
        "baseline_gas_threshold_ppm": 100.0,
        "ventilation_status": "nominal",
        "ventilation_flow_ratio": 1.0
    }
]

sensors = [
    {"sensor_id": "sensor-1", "zone_id": "zone-cnc", "modality": "gas", "unit": "ppm"},
    {"sensor_id": "sensor-2", "zone_id": "zone-hydraulic", "modality": "gas", "unit": "ppm"},
    {"sensor_id": "sensor-3", "zone_id": "zone-gas", "modality": "gas", "unit": "ppm"},
    {"sensor_id": "sensor-4", "zone_id": "zone-ppe", "modality": "gas", "unit": "ppm"},
    {"sensor_id": "sensor-5", "zone_id": "zone-control", "modality": "gas", "unit": "ppm"},
    {"sensor_id": "sensor-6", "zone_id": "zone-entrance", "modality": "gas", "unit": "ppm"},
    {"sensor_id": "sensor-auto-6", "zone_id": "zone-break", "modality": "gas", "unit": "ppm"}
]

# We will read the existing test_scenario and update it.
with open("scenarios/test_scenario.json", "r") as f:
    scenario = json.load(f)

scenario["zones"] = zones
scenario["sensors"] = sensors

# Ensure referential integrity by updating other fields to map to the new zones
scenario["zone_adjacency"] = [
    {"zone_a": "zone-gas", "zone_b": "zone-hydraulic", "medium": "ventilation_duct"}
]

scenario["assets"] = [
    {"asset_id": "COMP-H2-01", "zone_id": "zone-gas", "asset_type": "compressor", }
]

scenario["gas_readings"] = [
    {
        "sensor_id": "sensor-3",
        "zone_id": "zone-gas",
        "gas_type": "hydrogen",
        "concentration_ppm": 85.0,
        "severity": 0.55,
        "confidence": 0.88,
        "offset_seconds": 60
    },
    {
        "sensor_id": "sensor-3",
        "zone_id": "zone-gas",
        "gas_type": "hydrogen",
        "concentration_ppm": 120.0,
        "severity": 0.78,
        "confidence": 0.92,
        "offset_seconds": 180
    }
]

scenario["machine_readings"] = [
    {
        "asset_id": "COMP-H2-01",
        "zone_id": "zone-gas",
        "Type": "M",
        "Air_temperature": 68.5,
        "Process_temperature": 95.2,
        "Rotational_speed": 1420,
        "Torque": 48.3,
        "Tool_wear": 185,
        "offset_seconds": 30
    }
]

scenario["workers"] = [
    {
        "worker_id": "W-NS-01",
        "zone_id": "zone-gas",
        "present": True,
        "missing_ppe": ["gas_mask", "safety_glasses"]
    },
    {
        "worker_id": "W-NS-02",
        "zone_id": "zone-hydraulic",
        "present": True,
        "missing_ppe": []
    }
]

scenario["permits"] = [
    {
        "permit_id": "PTW-H2-NS-001",
        "zone_id": "zone-gas",
        "permit_type": "hot_work",
        "status": "active",
        "worker_id": "W-NS-02"
    }
]

scenario["metadata"]["expected_cut"] = [
    "Suspend PTW-H2-NS-001",
    "Evacuate W-NS-01 (no gas_mask)",
    "Restore ventilation to Gas Storage"
]

with open("scenarios/test_scenario.json", "w") as f:
    json.dump(scenario, f, indent=2)

print("Updated scenarios/test_scenario.json")
