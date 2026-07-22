import os
import pandas as pd
import numpy as np

def load_gas_batches(data_path: str, batches: list[int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """
    Loads the gas sensor drift dataset and extracts the specified batches.
    Returns unscaled X (features) and y (labels) suitable for the XGB training pipeline.
    
    Args:
        data_path: Path to the gas_sensors_drift.csv file.
        batches: List of batch integers to extract (e.g., [1, 2]). If None, loads all data.
        
    Returns:
        X: numpy array of shape (n_samples, 128)
        y: numpy array of shape (n_samples,) representing class labels (0 to 5)
    """
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Gas sensor dataset not found at: {data_path}")
        
    df = pd.read_csv(data_path)
    
    if batches is not None:
        batch_filenames = [f"batch{b}.dat" for b in batches]
        df = df[df["source_file"].isin(batch_filenames)]
        
    if df.empty:
        raise ValueError(f"No data found for batches: {batches}")
        
    # 'label' column is 1-indexed (1 to 6) based on UCI standard, we need to map it to 0-5
    # or ensure it matches the classifier expectations.
    # Assuming label column is named 'label' and is 1-6 integer.
    y = df['label'].values - 1  # 0-indexed for XGBoost
    
    # All other columns except 'label' and 'source_file' are features
    feature_cols = [c for c in df.columns if c not in ['label', 'source_file']]
    X = df[feature_cols].values
    
    return X, y

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, "gas_sensors_drift.csv")
    
    try:
        X, y = load_gas_batches(csv_path, batches=[1, 2])
        print(f"Loaded Batches 1 & 2. X shape: {X.shape}, y shape: {y.shape}")
        print(f"Unique classes found: {np.unique(y)}")
    except Exception as e:
        print(f"Failed to load dataset: {e}")
