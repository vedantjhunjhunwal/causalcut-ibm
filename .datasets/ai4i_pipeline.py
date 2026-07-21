import os
import urllib.request
import pandas as pd

def download_and_process(url, data_dir):
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        
    csv_path = os.path.join(data_dir, "ai4i2020.csv")
    
    if not os.path.exists(csv_path):
        print(f"Downloading from {url}...")
        try:
            urllib.request.urlretrieve(url, csv_path)
            print("Download complete.")
        except Exception as e:
            print(f"Failed to download: {e}")
            return
            
    print("Processing AI4I dataset...")
    df = pd.read_csv(csv_path)
    
    # AI4I has columns: UDI, Product ID, Type, Air temperature [K], Process temperature [K], 
    # Rotational speed [rpm], Torque [Nm], Tool wear [min], Machine failure, TWF, HDF, PWF, OSF, RNF
    
    # Drop IDs as they are not predictive
    if 'UDI' in df.columns:
        df = df.drop(columns=['UDI', 'Product ID'])
        
    # We will do One-Hot Encoding for 'Type' in the training pipeline or here.
    # It's better to keep the dataset raw and handle preprocessing in sklearn Pipeline, 
    # but the instructions usually prefer structured datasets. 
    # We'll just clean the column names to be Python friendly.
    df.columns = [c.replace(' [K]', '').replace(' [rpm]', '').replace(' [Nm]', '').replace(' [min]', '').replace(' ', '_') for c in df.columns]
    
    output_path = os.path.join(data_dir, "ai4i_processed.csv")
    df.to_csv(output_path, index=False)
    print(f"Processed dataset saved to {output_path} with shape {df.shape}")

if __name__ == "__main__":
    url = "https://archive.ics.uci.edu/ml/machine-learning-databases/00601/ai4i2020.csv"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, "ai4i")
    
    download_and_process(url, data_dir)
