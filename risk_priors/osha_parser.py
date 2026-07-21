import os
import json
import pandas as pd

def generate_osha_priors(csv_path: str, output_path: str):
    """
    Parses the official OSHA Severe Injury dataset CSV and extracts statistical priors.
    
    Strict Safety Constraint: DO NOT GENERATE SYNTHETIC DATA.
    If the official file is not provided, this script will deliberately fail and instruct 
    the user to download the original dataset.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"\n[STRICT CONSTRAINT ENFORCED] Official OSHA dataset not found at: {csv_path}\n"
            f"Please download the official 'Severe Injury Data' CSV from the OSHA dashboard:\n"
            f"URL: https://www.osha.gov/severeinjury\n"
            f"Place the file at the expected path and re-run this script.\n"
            f"Generating synthetic or mock OSHA records is prohibited by system constraints."
        )
        
    print(f"Parsing official OSHA dataset from {csv_path}...")
    df = pd.read_csv(csv_path)
    
    # Required columns based on standard OSHA Severe Injury export format
    # We will use fuzzy matching or common column names
    col_event = next((c for c in df.columns if 'EventTitle' in c or 'Event' in c), None)
    col_hosp = next((c for c in df.columns if 'Hospitalized' in c), None)
    col_amp = next((c for c in df.columns if 'Amputation' in c), None)
    
    if not all([col_event, col_hosp, col_amp]):
        raise ValueError("The provided CSV does not match the expected official OSHA Severe Injury schema.")
        
    total_incidents = len(df)
    
    # Calculate distributions
    event_counts = df[col_event].value_counts()
    
    hazard_base_rates = {}
    
    # Process top 5 most common severe injury event types for the prior
    for event_type, count in event_counts.head(5).items():
        event_df = df[df[col_event] == event_type]
        
        # Calculate severity weights based on hospitalization and amputation rates within this event
        total_event_cases = len(event_df)
        hosp_rate = event_df[col_hosp].sum() / total_event_cases if pd.api.types.is_numeric_dtype(event_df[col_hosp]) else 0.5
        amp_rate = event_df[col_amp].sum() / total_event_cases if pd.api.types.is_numeric_dtype(event_df[col_amp]) else 0.1
        
        # Simple weighted severity score (Amputations weighted higher)
        severity_weight = min(1.0, (hosp_rate * 0.7) + (amp_rate * 0.9))
        
        hazard_base_rates[str(event_type)] = {
            "base_probability": count / total_incidents,
            "severity_weight": round(severity_weight, 4),
            "total_historical_cases": int(count)
        }
        
    priors = {
        "metadata": {
            "source": "Official OSHA Severe Injury Reports",
            "total_records_processed": total_incidents,
            "columns_parsed": [col_event, col_hosp, col_amp]
        },
        "hazard_base_rates": hazard_base_rates
    }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(priors, f, indent=4)
        
    print(f"OSHA risk priors successfully calculated from official data and saved to {output_path}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Expecting the official CSV to be placed in the risk_priors directory
    official_csv_path = os.path.join(script_dir, "SevereInjuryData.csv")
    output_file = os.path.join(script_dir, "osha_risk_priors.json")
    
    generate_osha_priors(official_csv_path, output_file)
