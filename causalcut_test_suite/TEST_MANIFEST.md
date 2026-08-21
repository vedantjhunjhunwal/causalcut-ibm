# CAUSALCUT Test Suite

## Valid behavioral tests
01_baseline_reference — reference/reproducibility
02_all_nominal — false-positive / low-risk baseline
03_extreme_methane — extreme gas hazard
04_gas_near_threshold — boundary sensitivity around 100 ppm
05_machine_failure_extreme — extreme pump failure
06_ventilation_failure — failed extraction/ventilation
07_worker_ppe_compliant — remove PPE violation
08_multiple_worker_violations — multiple exposed workers
09_no_workers — no worker exposure
10_permit_inactive — inactive permit
11_permit_worker_mismatch — broken permit-worker relationship
12_no_permits — empty permit collection
13_low_sensor_confidence — uncertainty handling
14_disconnected_zones — no propagation across zones
15_duplicate_zone_edges — graph deduplication / double-count protection
16_missing_gas_reading — missing modality input
17_tracking_unavailable — tracking unavailable/degraded
18_empty_events — empty event store

## Invalid/schema robustness tests
invalid_01_threshold_string — wrong type
invalid_02_missing_scenario_id — required field missing
invalid_03_127_gas_features — wrong feature length
invalid_04_129_gas_features — wrong feature length
invalid_05_worker_present_string — wrong type
invalid_06_probability_out_of_range — probability outside [0,1]

## How to test
1. Upload one JSON at a time.
2. Save the complete CAUSALCUT output.
3. Send the output back for verification.
4. Compare model invocation, risk score, causal paths, propagation, minimum cut, residual risk, regulatory evidence, and audit/human-gate behavior.
5. Do not expect exact numeric scores from the manifest; verify qualitative behavior and consistency unless your implementation defines exact expected values.
