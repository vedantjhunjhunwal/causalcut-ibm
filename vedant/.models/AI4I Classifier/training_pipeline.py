import os
import joblib
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder
from sklearn.model_selection import RandomizedSearchCV
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import make_scorer, f1_score

def train_optimize_and_export_pipeline(
    data_path: str,
    export_dir: str,
    version_name: str = "lgbm-ai4i-1.0"
):
    print(f"Loading features from {data_path}...")
    df = pd.read_csv(data_path)
    
    target_cols = ['Machine_failure', 'TWF', 'HDF', 'PWF', 'OSF', 'RNF']
    
    X = df.drop(columns=target_cols)
    y_raw = df[target_cols]
    
    print(f"Feature shape: {X.shape}")
    
    # Identify continuous and categorical columns
    categorical_cols = ['Type']
    continuous_cols = ['Air_temperature', 'Process_temperature', 'Rotational_speed', 'Torque', 'Tool_wear']
    
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', MinMaxScaler(feature_range=(-1, 1)), continuous_cols),
            ('cat', OneHotEncoder(handle_unknown='ignore'), categorical_cols)
        ]
    )
    
    best_pipelines = {}
    
    for col in target_cols:
        print(f"\n--- Training for Target: {col} ---")
        y = y_raw[col].values
        
        # Base LightGBM classifier with balanced class weights
        lgb_estimator = lgb.LGBMClassifier(
            objective='binary',
            class_weight='balanced',
            n_jobs=1,
            random_state=42,
            verbosity=-1
        )
        
        pipeline = Pipeline([
            ('preprocessor', preprocessor),
            ('classifier', lgb_estimator)
        ])
        
        param_distributions = {
            'classifier__n_estimators': [50, 100, 200],
            'classifier__max_depth': [3, 5, 7],
            'classifier__learning_rate': [0.01, 0.05, 0.1],
            'classifier__num_leaves': [15, 31, 50],
            'classifier__min_child_samples': [10, 20, 30],
            'classifier__subsample': [0.8, 1.0],
            'classifier__colsample_bytree': [0.8, 1.0]
        }
        
        # Optimize for F1 macro score as instructed
        f1_scorer = make_scorer(f1_score, average='macro')
        
        random_search = RandomizedSearchCV(
            estimator=pipeline,
            param_distributions=param_distributions,
            n_iter=5, # Keep low for fast execution
            cv=3,
            scoring=f1_scorer,
            random_state=42,
            n_jobs=-1,
            verbose=1,
            refit=True
        )
        
        print("Running RandomizedSearchCV...")
        random_search.fit(X, y)
        print(f"Best parameters for {col}: {random_search.best_params_}")
        print(f"Best mean CV F1 score for {col}: {random_search.best_score_:.4f}")
        
        # Extract best parameters but we need a calibrated model.
        # CalibratedClassifierCV wraps an estimator and calibrates probabilities.
        # We can pass the fitted pipeline directly, but it's cleaner to clone the pipeline
        # with best parameters and then wrap the CLASSIFIER step, OR we can wrap the entire 
        # fitted pipeline. Wrapping the entire pipeline with cv='prefit' means we calibrate on 
        # the same data we trained on, which is a bit biased but works in a pinch.
        # However, to be rigorous, we wrap the un-fitted base estimator and let 
        # CalibratedClassifierCV do CV to calibrate.
        # We'll just wrap the best pipeline and use cv=3 for calibration.
        
        print("Calibrating probabilities via Platt scaling...")
        calibrated_pipeline = CalibratedClassifierCV(
            estimator=random_search.best_estimator_,
            method='sigmoid', # Platt scaling
            cv=3,
            n_jobs=-1
        )
        calibrated_pipeline.fit(X, y)
        
        best_pipelines[col] = calibrated_pipeline
    
    os.makedirs(export_dir, exist_ok=True)
    model_path = os.path.join(export_dir, f"{version_name}_pipelines.joblib")
    joblib.dump(best_pipelines, model_path)
    print(f"\nArtifact exported to: {model_path}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.dirname(os.path.dirname(script_dir))
    data_path = os.path.join(workspace_dir, ".datasets", "ai4i", "ai4i_processed.csv")
    
    if not os.path.exists(data_path):
        print(f"Error: Data file not found at {data_path}")
    else:
        train_optimize_and_export_pipeline(data_path, script_dir)
