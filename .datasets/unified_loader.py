import os
import pandas as pd
import numpy as np

# Import specific loader functions
from .gas_sensor_pipeline import load_gas_batches

class UnifiedDataLoader:
    """
    A unified interface for loading all CAUSALCUT datasets.
    Abstracts away the underlying directory structures and specific preprocessing rules.
    """
    
    def __init__(self, datasets_dir: str = None):
        if datasets_dir is None:
            self.datasets_dir = os.path.dirname(os.path.abspath(__file__))
        else:
            self.datasets_dir = datasets_dir
            
    def get_gas_sensor_batch(self, batches: list[int]) -> tuple[np.ndarray, np.ndarray]:
        """Loads specific batches from the UCI Gas Sensor Drift dataset."""
        csv_path = os.path.join(self.datasets_dir, "gas_sensors_drift.csv")
        return load_gas_batches(csv_path, batches)
        
    def get_ai4i_data(self) -> pd.DataFrame:
        """Loads the processed AI4I Predictive Maintenance dataset."""
        csv_path = os.path.join(self.datasets_dir, "ai4i", "ai4i_processed.csv")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"AI4I dataset not found at {csv_path}. Run ai4i_pipeline.py first.")
        return pd.read_csv(csv_path)
        
    def get_hydraulic_data(self) -> pd.DataFrame:
        """Loads the processed UCI Hydraulic Condition Monitoring dataset."""
        csv_path = os.path.join(self.datasets_dir, "hydraulic", "hydraulic_features.csv")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Hydraulic dataset not found at {csv_path}. Run hydraulic_pipeline.py first.")
        return pd.read_csv(csv_path)

if __name__ == "__main__":
    loader = UnifiedDataLoader()
    try:
        df_ai4i = loader.get_ai4i_data()
        print(f"AI4I Data Shape: {df_ai4i.shape}")
    except Exception as e:
        print(e)
