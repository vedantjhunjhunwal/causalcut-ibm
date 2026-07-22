import os
import joblib
import pandas as pd
import numpy as np

def load_artifacts(model_dir: str, version_name: str = "lgbm-ai4i-1.0"):
    pipelines_path = os.path.join(model_dir, f"{version_name}_pipelines.joblib")
    
    if not os.path.exists(pipelines_path):
        raise FileNotFoundError("Model artifacts not found. Please run training_pipeline.py first.")
        
    pipelines = joblib.load(pipelines_path)
    return pipelines

def predict_probabilities(pipelines, features_df: pd.DataFrame) -> dict:
    """
    Runs inference and returns failure probability for each mode.
    """
    results = {}
    for col, pipeline in pipelines.items():
        # predict_proba returns [prob_negative, prob_positive]
        prob = pipeline.predict_proba(features_df)[0][1]
        results[col] = float(prob)
        
    return results

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("Loading AI4I artifacts...")
    try:
        pipelines = load_artifacts(script_dir)
        print("Artifacts loaded successfully.")
        
        # Create dummy sample
        print("\nSimulating inference on a dummy sample...")
        
        dummy_data = pd.DataFrame([{
            'Type': 'M',
            'Air_temperature': 298.1,
            'Process_temperature': 308.6,
            'Rotational_speed': 1551,
            'Torque': 42.8,
            'Tool_wear': 0
        }])
        
        preds = predict_probabilities(pipelines, dummy_data)
        
        print("\nPredicted Failure Probabilities (Calibrated):")
        for k, v in preds.items():
            print(f"  {k}: {v:.4f} ({v*100:.2f}%)")
            
    except Exception as e:
        print(f"Error during inference testing: {e}")
