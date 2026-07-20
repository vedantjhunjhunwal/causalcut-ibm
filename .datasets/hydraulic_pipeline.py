import os
import urllib.request
import zipfile
import pandas as pd
import numpy as np
from scipy.stats import skew, kurtosis

def download_and_extract(url, extract_to):
    if not os.path.exists(extract_to):
        os.makedirs(extract_to)
    
    zip_path = os.path.join(extract_to, "dataset.zip")
    if not os.path.exists(zip_path):
        print(f"Downloading from {url}...")
        urllib.request.urlretrieve(url, zip_path)
        print("Download complete.")
        
    print("Extracting...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    print("Extraction complete.")

def extract_features(data_dir):
    print("Extracting features from sensor data...")
    # List of sensors (txt files in the dataset)
    sensors = [
        'PS1', 'PS2', 'PS3', 'PS4', 'PS5', 'PS6',
        'EPS1', 'FS1', 'FS2', 'TS1', 'TS2', 'TS3', 'TS4',
        'VS1', 'CE', 'CP', 'SE'
    ]
    
    features_list = []
    
    # Read each sensor file
    # Each file has 2205 rows (cycles) and N columns (measurements in that cycle)
    sensor_data = {}
    for sensor in sensors:
        file_path = os.path.join(data_dir, f"{sensor}.txt")
        # Load data, separated by tabs
        try:
            df = pd.read_csv(file_path, sep='\t', header=None)
            sensor_data[sensor] = df.values
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return None

    num_cycles = sensor_data['PS1'].shape[0]
    
    for i in range(num_cycles):
        cycle_features = {}
        for sensor in sensors:
            row_data = sensor_data[sensor][i]
            cycle_features[f'{sensor}_mean'] = np.mean(row_data)
            cycle_features[f'{sensor}_median'] = np.median(row_data)
            cycle_features[f'{sensor}_max'] = np.max(row_data)
            cycle_features[f'{sensor}_min'] = np.min(row_data)
            cycle_features[f'{sensor}_std'] = np.std(row_data)
            cycle_features[f'{sensor}_skew'] = skew(row_data)
        features_list.append(cycle_features)
        
    features_df = pd.DataFrame(features_list)
    
    print("Loading target profile...")
    # profile.txt contains 5 columns:
    # 1: Cooler condition / %: 3, 20, 100
    # 2: Valve condition / %: 100, 73, 80, 90
    # 3: Internal pump leakage: 0, 1, 2
    # 4: Hydraulic accumulator / bar: 130, 115, 100, 90
    # 5: stable flag: 0, 1
    profile_path = os.path.join(data_dir, "profile.txt")
    target_names = ['Cooler_Condition', 'Valve_Condition', 'Pump_Leakage', 'Accumulator_Pressure', 'Stable_Flag']
    targets_df = pd.read_csv(profile_path, sep='\t', header=None, names=target_names)
    
    # Combine
    final_df = pd.concat([targets_df, features_df], axis=1)
    
    output_csv = os.path.join(data_dir, "hydraulic_features.csv")
    final_df.to_csv(output_csv, index=False)
    print(f"Feature dataset saved to {output_csv} with shape {final_df.shape}")

if __name__ == "__main__":
    url = "https://archive.ics.uci.edu/static/public/447/condition+monitoring+of+hydraulic+systems.zip"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    extract_to = os.path.join(script_dir, "hydraulic")
    
    download_and_extract(url, extract_to)
    extract_features(extract_to)
