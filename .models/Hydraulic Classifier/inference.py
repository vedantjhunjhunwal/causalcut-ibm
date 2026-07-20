import os
import joblib
import pandas as pd
import numpy as np
from scipy.stats import skew

def load_artifacts(model_dir: str, version_name: str = "lgbm-hydraulic-1.0"):
    pipelines_path = os.path.join(model_dir, f"{version_name}_pipelines.joblib")
    encoders_path = os.path.join(model_dir, f"{version_name}_encoders.joblib")
    
    if not os.path.exists(pipelines_path) or not os.path.exists(encoders_path):
        raise FileNotFoundError("Model artifacts not found. Please run training_pipeline.py first.")
        
    pipelines = joblib.load(pipelines_path)
    encoders = joblib.load(encoders_path)
    return pipelines, encoders

def extract_features_for_cycle(sensor_data: dict) -> pd.DataFrame:
    """
    Given a dictionary of sensor arrays for a single cycle, extract statistical features.
    sensor_data = {
        'PS1': np.array([...]),
        'PS2': np.array([...]),
        ...
    }
    """
    sensors = [
        'PS1', 'PS2', 'PS3', 'PS4', 'PS5', 'PS6',
        'EPS1', 'FS1', 'FS2', 'TS1', 'TS2', 'TS3', 'TS4',
        'VS1', 'CE', 'CP', 'SE'
    ]
    
    cycle_features = {}
    for sensor in sensors:
        if sensor not in sensor_data:
            raise ValueError(f"Missing sensor data for {sensor}")
        
        row_data = sensor_data[sensor]
        cycle_features[f'{sensor}_mean'] = np.mean(row_data)
        cycle_features[f'{sensor}_median'] = np.median(row_data)
        cycle_features[f'{sensor}_max'] = np.max(row_data)
        cycle_features[f'{sensor}_min'] = np.min(row_data)
        cycle_features[f'{sensor}_std'] = np.std(row_data)
        cycle_features[f'{sensor}_skew'] = skew(row_data)
        
    return pd.DataFrame([cycle_features])

def predict(pipelines, encoders, features_df: pd.DataFrame) -> dict:
    """
    Runs inference on the extracted features and decodes the target labels.
    """
    results = {}
    for col, pipeline in pipelines.items():
        le = encoders[col]
        pred_encoded = pipeline.predict(features_df)[0]
        decoded_val = le.inverse_transform([int(pred_encoded)])[0]
        results[col] = decoded_val
        
    return results

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("Loading artifacts...")
    try:
        pipelines, encoders = load_artifacts(script_dir)
        print("Artifacts loaded successfully.")
        
        # Create dummy sensor data to simulate one cycle
        print("\nSimulating inference on a dummy cycle...")
        sensors = [
            'PS1', 'PS2', 'PS3', 'PS4', 'PS5', 'PS6',
            'EPS1', 'FS1', 'FS2', 'TS1', 'TS2', 'TS3', 'TS4',
            'VS1', 'CE', 'CP', 'SE'
        ]
        
        dummy_data = {}
        np.random.seed(42)
        for s in sensors:
            dummy_data[s] = np.random.rand(100) * 100 
            
        features = extract_features_for_cycle(dummy_data)
        preds = predict(pipelines, encoders, features)
        
        print("\nPredictions for dummy cycle:")
        for k, v in preds.items():
            print(f"  {k}: {v}")
            
    except Exception as e:
        print(f"Error during inference testing: {e}")
