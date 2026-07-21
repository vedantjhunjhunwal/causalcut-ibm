import os
import joblib
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler, LabelEncoder
from sklearn.model_selection import RandomizedSearchCV

def train_optimize_and_export_pipeline(
    data_path: str,
    export_dir: str,
    version_name: str = "lgbm-hydraulic-1.0"
):
    print(f"Loading features from {data_path}...")
    df = pd.read_csv(data_path)
    
    target_cols = ['Cooler_Condition', 'Valve_Condition', 'Pump_Leakage', 'Accumulator_Pressure', 'Stable_Flag']
    
    X = df.drop(columns=target_cols)
    y_raw = df[target_cols]
    
    encoders = {}
    best_pipelines = {}
    
    print(f"Feature shape: {X.shape}")
    
    for col in target_cols:
        print(f"\n--- Training for Target: {col} ---")
        le = LabelEncoder()
        y_encoded = le.fit_transform(y_raw[col])
        encoders[col] = le
        num_classes = len(le.classes_)
        print(f"Classes mapped: {le.classes_} -> {np.arange(num_classes)}")
        
        # Determine objective
        if num_classes > 2:
            objective = 'multiclass'
        else:
            objective = 'binary'

        lgb_estimator = lgb.LGBMClassifier(
            objective=objective,
            num_class=num_classes if num_classes > 2 else 1,
            n_jobs=1,
            random_state=42,
            verbosity=-1
        )
        
        pipeline = Pipeline([
            ('scaler', MinMaxScaler(feature_range=(-1, 1))),
            ('classifier', lgb_estimator)
        ])
        
        param_distributions = {
            'classifier__n_estimators': [50, 100, 200],
            'classifier__max_depth': [3, 5, 7],
            'classifier__learning_rate': [0.01, 0.05, 0.1],
            'classifier__num_leaves': [20, 31, 40],
            'classifier__min_child_samples': [10, 20, 30],
            'classifier__subsample': [0.8, 1.0],
            'classifier__colsample_bytree': [0.8, 1.0]
        }
        
        random_search = RandomizedSearchCV(
            estimator=pipeline,
            param_distributions=param_distributions,
            n_iter=5, # Reduced iterations for speed
            cv=3,
            random_state=42,
            n_jobs=-1,
            verbose=1,
            refit=True
        )
        
        random_search.fit(X, y_encoded)
        
        print(f"Best parameters for {col}: {random_search.best_params_}")
        print(f"Best mean CV score (accuracy) for {col}: {random_search.best_score_:.4f}")
        
        best_pipelines[col] = random_search.best_estimator_
    
    os.makedirs(export_dir, exist_ok=True)
    
    model_path = os.path.join(export_dir, f"{version_name}_pipelines.joblib")
    encoders_path = os.path.join(export_dir, f"{version_name}_encoders.joblib")
    
    joblib.dump(best_pipelines, model_path)
    joblib.dump(encoders, encoders_path)
    
    print(f"\nArtifacts exported to:\n  - {model_path}\n  - {encoders_path}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.dirname(os.path.dirname(script_dir))
    data_path = os.path.join(workspace_dir, ".datasets", "hydraulic", "hydraulic_features.csv")
    
    if not os.path.exists(data_path):
        print(f"Error: Data file not found at {data_path}")
        print("Please run the hydraulic_pipeline.py script first.")
    else:
        train_optimize_and_export_pipeline(data_path, script_dir)
