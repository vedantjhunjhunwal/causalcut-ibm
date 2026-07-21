OISD_DOCUMENTS = [
    {
        "doc_id": "OISD-STD-116",
        "source_type": "oisd_standard",
        "title": "Fire Protection Facilities for Petroleum Refineries and Oil/Gas Processing Plants",
        "text": """
Clause 4.0: General Fire Protection Requirements

4.1 Every petroleum refinery, oil and gas processing plant, and petrochemical complex shall have a comprehensive fire protection system designed to detect, control, and extinguish fires. The fire protection philosophy shall be based on a fire risk assessment considering the nature and quantity of hydrocarbons processed, stored, and handled at the facility.

4.2 Fire protection systems shall be designed to limit the consequences of fire to the immediate vicinity of the incident, prevent escalation to adjacent units, and provide adequate time for safe evacuation of personnel. Passive fire protection such as fireproofing of structural steel, fire walls, and blast walls shall be provided in addition to active fire protection systems.

Clause 4.3: Hot Work Permit Suspension

All hot work permits shall be immediately suspended in the event of any combustible gas alarm or confirmed gas detection in the vicinity. The hot work permit authority must physically verify the site and ensure gas concentrations are below 10% of the Lower Explosive Limit (LEL) before re-issuing or resuming the hot work permit. Any ongoing welding, cutting, or grinding operations must cease immediately upon sounding of the emergency alarm. The hot work area must be continuously monitored by a dedicated fire watch for a minimum of 30 minutes after completion of hot work activities.

4.4 A fire watch shall be posted during all hot work operations. The fire watch person shall be equipped with appropriate fire extinguishing equipment and communication devices. The fire watch shall remain at the hot work location for a minimum of 30 minutes after completion of hot work to detect and extinguish any smouldering material.

Clause 5.0: Fire Water Systems

Clause 5.1: Fire Water Network and Supply

A robust fire water ring main network must be established and maintained at a continuous pressure of not less than 7 kg/cm2g at the hydraulically farthest point. The fire water storage capacity must be sufficient to meet the maximum fire water demand for a minimum duration of 4 hours. Dedicated fire water pumps, including diesel-driven standby pumps, must be periodically tested at rated capacity. The fire water system shall be independent of the plant process water and cooling water systems.

5.2 Fire hydrants shall be spaced at intervals not exceeding 30 metres along the ring main in process areas and 45 metres in tank farm areas. Each hydrant shall be capable of delivering not less than 1800 litres per minute at the rated pressure. Hydrant connections shall be standardised to ensure compatibility with fire brigade equipment.

5.3 Fixed water spray systems shall be installed for the protection of LPG spheres, bullet tanks, and other pressurised hydrocarbon storage vessels. The application rate shall not be less than 10.2 litres per minute per square metre of the total exposed surface area.

Clause 6.0: Fire Detection and Alarm System

Clause 6.1: General Requirements for Fire Detection

Fire detection systems shall be designed to provide earliest possible detection of fire conditions in all areas of the facility. The detection system shall be zoned to provide precise identification of the fire location. All detection signals shall be annunciated in the main control room and the fire station.

Clause 6.2: Fire Detection Systems

Automatic fire detection systems, utilizing thermal, smoke, and flame detectors, shall be installed in all critical process areas, control rooms, cable galleries, and electrical substations. Multi-spectrum infrared flame detectors shall be used in outdoor hydrocarbon processing areas. Linear heat detection cables shall be installed along cable trays and in areas where point-type detectors are impractical. Cross-zoning or voting logic should be implemented to prevent false activation of fixed fire suppression systems while maintaining rapid response to genuine fire events.

6.3 Manual call points shall be provided at all exit routes and at intervals not exceeding 30 metres in process areas. The fire alarm system shall be audible throughout the facility, supplemented by visual alarm indicators in high-noise areas. The fire alarm system shall be connected to an uninterruptible power supply with a minimum battery backup of 24 hours in standby plus 30 minutes in alarm condition.
"""
    },
    {
        "doc_id": "OISD-STD-154",
        "source_type": "oisd_standard",
        "title": "Safety Instrumented Systems",
        "text": """
Clause 3.0: SIS Requirements

Clause 3.1: Fundamental Requirements for Safety Instrumented Systems (SIS)

The Safety Instrumented System (SIS) shall be designed, engineered, and maintained completely independent of the Basic Process Control System (BPCS). The SIS must have redundant architecture where high availability and reliability are required. Fail-safe logic must be employed such that any component failure drives the process to a known safe state. The SIS shall be designed in accordance with IEC 61508 and IEC 61511 standards.

3.2 The SIS shall have separate sensors, logic solvers, and final elements from those used by the BPCS. Where common sensors are used for both BPCS and SIS functions, the integrity of the SIS signal shall not be compromised by BPCS demands. All SIS components shall be clearly identified and tagged with a unique SIS equipment number distinguishable from BPCS equipment.

3.3 Diagnostic coverage shall be a key design parameter. Online diagnostics shall detect at least 90% of dangerous failures for SIL 2 applications and 99% for SIL 3 applications. Detected dangerous failures shall be annunciated and automatically logged. The mean time to restoration (MTTR) after a dangerous detected failure shall not exceed 8 hours.

Clause 4.0: Safety Integrity Levels (SIL)

Clause 4.1: SIL Classification

Safety Integrity Levels (SIL) are classified from SIL 1 (lowest) to SIL 4 (highest). SIL 1 requires a Probability of Failure on Demand (PFD) of less than 0.1, SIL 2 requires PFD less than 0.01, SIL 3 requires PFD less than 0.001, and SIL 4 requires PFD less than 0.0001. Most industrial applications fall within SIL 1 to SIL 3. SIL 4 is reserved for nuclear and similar ultra-high-consequence applications.

Clause 4.2: SIL Assessment and Allocation

A formal Risk Assessment using techniques such as Layers of Protection Analysis (LOPA) or Quantitative Risk Assessment (QRA) shall be conducted to determine the required Safety Integrity Level (SIL) for each Safety Instrumented Function (SIF). The SIL rating must dictate the required Probability of Failure on Demand (PFD) and hardware fault tolerance. Regular proof testing must be scheduled and executed to maintain the allocated SIL over the plant lifecycle. Proof test intervals shall be determined through reliability analysis and shall not exceed the intervals assumed in the SIL verification calculations.

4.3 Management of Change (MOC) procedures shall apply to all modifications to the SIS, including changes to setpoints, logic, instrument ranges, or proof test intervals. No change to the SIS shall be implemented without a documented safety review. Temporary bypasses or overrides of SIS functions shall be subject to formal authorization, time-limited, and continuously monitored.
"""
    },
    {
        "doc_id": "OISD-STD-144",
        "source_type": "oisd_standard",
        "title": "Petroleum Industry Gas Detection and Alarm Systems",
        "text": """
Clause 3.0: Detector Siting and Placement

Clause 3.1: General Siting Principles

Gas detectors shall be located at potential leak sources and in areas where gas accumulation is likely. The detector network design shall consider the plant layout, process conditions, prevailing wind conditions, and the physical and chemical properties of the target gases. A formal gas detector mapping study shall be conducted as part of the plant design.

Clause 3.2: Gas Detector Placement

Combustible and toxic gas detectors shall be located considering the specific gravity of the target gas relative to air. For lighter-than-air gases such as hydrogen and methane, detectors must be placed at high elevations or above potential leak sources. For heavier-than-air gases such as LPG and H2S, detectors must be located near the ground level or in trenches and pits. Placement must also account for prevailing wind direction, ventilation patterns, and process equipment density. A minimum of two detectors shall be provided at each critical monitoring location to provide redundancy.

3.3 In enclosed or semi-enclosed areas, detectors shall be positioned considering the ventilation flow pattern to detect gas at the earliest opportunity. Detectors shall not be placed in dead zones where air movement is insufficient to transport the target gas to the sensing element. Detector spacing in open process areas shall not exceed 5 metres radius for point-type detectors.

Clause 4.0: Alarm Configuration

Clause 4.1: Alarm Setpoints for Gas Detectors

Combustible gas detectors shall have two alarm levels: High Alarm set at 20% LEL and High-High Alarm set at 40% LEL. High Alarms shall trigger visual and audible alarms in the control room and initiate operator response. High-High Alarms shall trigger automatic executive actions such as isolation of feed valves, shutdown of non-essential equipment, or initiation of emergency blowdown. Toxic gas detectors for H2S shall have alarm setpoints at the Threshold Limit Value Time Weighted Average (TLV-TWA) of 10 ppm and Short Term Exposure Limit (STEL) of 15 ppm.

4.2 Alarm rationalization shall be conducted to prevent alarm flooding. The number of alarms presented to the operator during an emergency shall be manageable. Priority-based alarm presentation shall be implemented with critical safety alarms given the highest priority and most prominent display.

Clause 5.0: Maintenance and Testing

Clause 5.1: Routine Maintenance

A documented maintenance programme shall be established for all gas detection equipment. Routine maintenance shall include visual inspection, functional testing, and cleaning of detector heads. Maintenance activities shall be performed by trained and competent personnel.

Clause 5.2: Periodic Functional Testing

Gas detectors shall be functionally tested at intervals not exceeding one month to verify correct operation. Functional testing shall include application of a known concentration of test gas and verification that the detector output corresponds to the expected reading within the specified accuracy tolerance.

Clause 5.3: Calibration

All gas detectors shall be subject to a strict calibration regime. Calibration using standard span gas mixtures traceable to national standards must be performed at least once every three months. Sensor response times and output signals to the control room must be verified during calibration. A documented history of all calibrations, sensor replacements, and malfunctions shall be maintained for audits and regulatory inspections. Detectors that fail calibration shall be replaced immediately.
"""
    },
    {
        "doc_id": "OISD-GDN-206",
        "source_type": "oisd_standard",
        "title": "Guidelines on Safety Management System",
        "text": """
Clause 3.0: Operational Controls

Clause 3.1: General Operational Safety

Safe operating procedures shall be developed for all routine and non-routine activities. These procedures shall be written in a language understood by the workers and shall be readily accessible at the workstation. Procedures shall be reviewed and updated at least annually or whenever there is a change in process, equipment, or organizational structure.

3.2 Pre-startup safety reviews shall be conducted before commissioning of new facilities, after major turnarounds, or after significant process modifications. The review shall verify that all construction, modifications, and maintenance activities have been completed in accordance with design specifications and applicable standards.

3.3 Operating limits and critical process parameters shall be clearly defined and displayed at the operator workstation. Deviations from safe operating limits shall trigger appropriate alarms and response actions as defined in the operating procedures.

Clause 3.4: Permit-To-Work (PTW) System

A stringent Permit-To-Work system is mandatory for all non-routine activities including hot work, confined space entry, working at heights, excavation, and electrical isolation. The PTW must clearly document the hazard identification, required PPE, isolation boundaries using Lockout/Tagout mechanisms, and gas test results. It must be authorized by the facility manager and acknowledged by the executing agency. No work shall commence until the permit is signed by all required authorities.

3.5 A central permit coordination system shall be maintained to track all active permits. Permits for simultaneous activities in the same area shall be cross-referenced. The PTW system shall include provisions for suspension of permits when conditions change, shift handover of active permits, and formal closure upon completion of work.

Clause 4.0: Risk Management

Clause 4.1: Risk Assessment Process

A comprehensive hazard identification and risk assessment (HIRA) must be performed for all routine and non-routine operations. Techniques such as HAZOP, HAZID, What-If analysis, Fault Tree Analysis, and Event Tree Analysis shall be employed as appropriate. Mitigation strategies shall follow the hierarchy of controls: elimination, substitution, engineering controls, administrative controls, and PPE. Risks must be reduced to As Low As Reasonably Practicable (ALARP). Risk assessments shall be reviewed periodically and updated after incidents, near-misses, or significant changes.

4.2 A formal Management of Change (MOC) process shall be established. All changes to process, equipment, procedures, organizational structure, or raw materials shall be evaluated for safety implications before implementation. Temporary changes shall be subject to the same rigor as permanent changes and shall have defined expiry dates.

Clause 5.0: Emergency Preparedness

Clause 5.1: Emergency Organization

An emergency response organization shall be established with clearly defined roles, responsibilities, and authority. The Incident Commander shall have the authority to mobilize all necessary resources and make critical decisions during an emergency. Communication channels shall be established between the incident site, control room, emergency response team, management, and external agencies.

Clause 5.2: Emergency Planning

An On-Site Emergency Plan (OSEP) must be developed in accordance with the requirements of the Factories Act 1948 and applicable state rules, detailing the roles and responsibilities of the Incident Management Team, emergency response procedures for all credible emergency scenarios, mutual aid arrangements with neighbouring facilities, and interface with the District Emergency Plan (Off-Site Plan). Evacuation routes and assembly points must be clearly marked and illuminated. Mock drills covering scenarios such as major fire, toxic gas release, explosion, and structural collapse shall be conducted at least bi-annually to evaluate the effectiveness of the emergency plan.

5.3 Emergency equipment including breathing apparatus, fire tenders, ambulances, and emergency communication systems shall be tested and inspected at defined intervals. Emergency response personnel shall undergo regular refresher training. Post-emergency reviews shall be conducted after every actual emergency and major drill to identify areas for improvement.
"""
    }
]
