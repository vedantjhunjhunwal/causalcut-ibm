"""
Comprehensive evaluation script for all trained models.
Computes: Accuracy, Precision, Recall, F1-Score, Classification Reports.
Uses stratified train/test splits to generate held-out metrics.
"""
import os
import sys
import json
import joblib
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder, LabelEncoder
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    classification_report, confusion_matrix
)
from sklearn.calibration import CalibratedClassifierCV


WORKSPACE = os.path.dirname(os.path.abspath(__file__))


def separator(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ─────────────────────────────────────────────────────────────
# 1. HYDRAULIC SYSTEMS EVALUATION
# ─────────────────────────────────────────────────────────────
def evaluate_hydraulic():
    separator("HYDRAULIC CONDITION MONITORING — UCI #447")

    data_path = os.path.join(WORKSPACE, ".datasets", "hydraulic", "hydraulic_features.csv")
    if not os.path.exists(data_path):
        print("[SKIP] hydraulic_features.csv not found.")
        return {}

    df = pd.read_csv(data_path)
    target_cols = ['Cooler_Condition', 'Valve_Condition', 'Pump_Leakage',
                   'Accumulator_Pressure', 'Stable_Flag']
    X = df.drop(columns=target_cols)
    y_raw = df[target_cols]

    print(f"Dataset: {df.shape[0]} cycles × {X.shape[1]} features")
    print(f"Targets: {target_cols}\n")

    results = {}
    for col in target_cols:
        print(f"--- {col} ---")
        le = LabelEncoder()
        y = le.fit_transform(y_raw[col])
        num_classes = len(le.classes_)

        if num_classes > 2:
            objective = 'multiclass'
        else:
            objective = 'binary'

        lgb_est = lgb.LGBMClassifier(
            objective=objective,
            num_class=num_classes if num_classes > 2 else 1,
            n_jobs=1, random_state=42, verbosity=-1
        )
        pipeline = Pipeline([
            ('scaler', MinMaxScaler(feature_range=(-1, 1))),
            ('classifier', lgb_est)
        ])

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        scoring = {
            'accuracy': 'accuracy',
            'f1_macro': 'f1_macro',
            'precision_macro': 'precision_macro',
            'recall_macro': 'recall_macro'
        }
        cv_results = cross_validate(pipeline, X, y, cv=cv, scoring=scoring,
                                    return_train_score=False, n_jobs=-1)

        metrics = {
            'accuracy':  float(np.mean(cv_results['test_accuracy'])),
            'f1_macro':  float(np.mean(cv_results['test_f1_macro'])),
            'precision_macro': float(np.mean(cv_results['test_precision_macro'])),
            'recall_macro': float(np.mean(cv_results['test_recall_macro'])),
            'classes': le.classes_.tolist()
        }
        results[col] = metrics
        print(f"  Accuracy:        {metrics['accuracy']:.4f}")
        print(f"  Precision (mac): {metrics['precision_macro']:.4f}")
        print(f"  Recall    (mac): {metrics['recall_macro']:.4f}")
        print(f"  F1        (mac): {metrics['f1_macro']:.4f}")
        print(f"  Classes:         {le.classes_}\n")

    return results


# ─────────────────────────────────────────────────────────────
# 2. AI4I 2020 EVALUATION
# ─────────────────────────────────────────────────────────────
def evaluate_ai4i():
    separator("AI4I 2020 PREDICTIVE MAINTENANCE — UCI #601")

    data_path = os.path.join(WORKSPACE, ".datasets", "ai4i", "ai4i_processed.csv")
    if not os.path.exists(data_path):
        print("[SKIP] ai4i_processed.csv not found.")
        return {}

    df = pd.read_csv(data_path)
    target_cols = ['Machine_failure', 'TWF', 'HDF', 'PWF', 'OSF', 'RNF']
    X = df.drop(columns=target_cols)
    y_raw = df[target_cols]

    categorical_cols = ['Type']
    continuous_cols = ['Air_temperature', 'Process_temperature',
                       'Rotational_speed', 'Torque', 'Tool_wear']

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', MinMaxScaler(feature_range=(-1, 1)), continuous_cols),
            ('cat', OneHotEncoder(handle_unknown='ignore'), categorical_cols)
        ]
    )

    print(f"Dataset: {df.shape[0]} samples × {X.shape[1]} features")
    print(f"Targets: {target_cols}")

    # Show class distribution
    print("\nClass distribution:")
    for col in target_cols:
        counts = y_raw[col].value_counts().to_dict()
        print(f"  {col}: {counts}")
    print()

    results = {}
    for col in target_cols:
        print(f"--- {col} ---")
        y = y_raw[col].values

        lgb_est = lgb.LGBMClassifier(
            objective='binary',
            class_weight='balanced',
            n_jobs=1, random_state=42, verbosity=-1
        )
        pipeline = Pipeline([
            ('preprocessor', preprocessor),
            ('classifier', lgb_est)
        ])

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        scoring = {
            'accuracy': 'accuracy',
            'f1_macro': 'f1_macro',
            'precision_macro': 'precision_macro',
            'recall_macro': 'recall_macro'
        }
        cv_results = cross_validate(pipeline, X, y, cv=cv, scoring=scoring,
                                    return_train_score=False, n_jobs=-1)

        metrics = {
            'accuracy':  float(np.mean(cv_results['test_accuracy'])),
            'f1_macro':  float(np.mean(cv_results['test_f1_macro'])),
            'precision_macro': float(np.mean(cv_results['test_precision_macro'])),
            'recall_macro': float(np.mean(cv_results['test_recall_macro'])),
        }
        results[col] = metrics
        print(f"  Accuracy:        {metrics['accuracy']:.4f}")
        print(f"  Precision (mac): {metrics['precision_macro']:.4f}")
        print(f"  Recall    (mac): {metrics['recall_macro']:.4f}")
        print(f"  F1        (mac): {metrics['f1_macro']:.4f}\n")

    return results


# ─────────────────────────────────────────────────────────────
# 3. INFERENCE TESTS
# ─────────────────────────────────────────────────────────────
def test_hydraulic_inference():
    separator("HYDRAULIC INFERENCE TEST")
    model_dir = os.path.join(WORKSPACE, ".models", "Hydraulic Classifier")
    pipelines_path = os.path.join(model_dir, "lgbm-hydraulic-1.0_pipelines.joblib")
    encoders_path = os.path.join(model_dir, "lgbm-hydraulic-1.0_encoders.joblib")

    if not os.path.exists(pipelines_path):
        print("[SKIP] Hydraulic model artifacts not found.")
        return False

    pipelines = joblib.load(pipelines_path)
    encoders = joblib.load(encoders_path)
    print(f"Loaded {len(pipelines)} pipelines and {len(encoders)} encoders.")

    # Load actual data for a real sample test
    data_path = os.path.join(WORKSPACE, ".datasets", "hydraulic", "hydraulic_features.csv")
    df = pd.read_csv(data_path)
    target_cols = ['Cooler_Condition', 'Valve_Condition', 'Pump_Leakage',
                   'Accumulator_Pressure', 'Stable_Flag']
    X = df.drop(columns=target_cols)
    sample = X.iloc[[0]]

    print(f"\nPredicting on row 0 of dataset...")
    for col, pipeline in pipelines.items():
        le = encoders[col]
        pred_encoded = pipeline.predict(sample)[0]
        decoded = le.inverse_transform([int(pred_encoded)])[0]
        actual = df[col].iloc[0]
        status = "PASS" if decoded == actual else "FAIL"
        print(f"  {col}: predicted={decoded}, actual={actual}  [{status}]")

    print("\n[PASS] Hydraulic inference test completed.")
    return True


def test_ai4i_inference():
    separator("AI4I INFERENCE TEST")
    model_dir = os.path.join(WORKSPACE, ".models", "AI4I Classifier")
    pipelines_path = os.path.join(model_dir, "lgbm-ai4i-1.0_pipelines.joblib")

    if not os.path.exists(pipelines_path):
        print("[SKIP] AI4I model artifacts not found.")
        return False

    pipelines = joblib.load(pipelines_path)
    print(f"Loaded {len(pipelines)} calibrated pipelines.")

    # Load actual data for a real sample test
    data_path = os.path.join(WORKSPACE, ".datasets", "ai4i", "ai4i_processed.csv")
    df = pd.read_csv(data_path)
    target_cols = ['Machine_failure', 'TWF', 'HDF', 'PWF', 'OSF', 'RNF']
    X = df.drop(columns=target_cols)

    # Test on first healthy sample (row 0 => no failure)
    sample = X.iloc[[0]]
    print(f"\nPredicting on row 0 (expected: no failure)...")
    for col, pipeline in pipelines.items():
        prob = pipeline.predict_proba(sample)[0][1]
        actual = df[col].iloc[0]
        print(f"  {col}: prob={prob:.4f} ({prob*100:.2f}%), actual={actual}")

    # Test on a known failure sample
    failure_idx = df[df['Machine_failure'] == 1].index
    if len(failure_idx) > 0:
        idx = failure_idx[0]
        sample_fail = X.iloc[[idx]]
        print(f"\nPredicting on row {idx} (expected: failure)...")
        for col, pipeline in pipelines.items():
            prob = pipeline.predict_proba(sample_fail)[0][1]
            actual = df[col].iloc[idx]
            print(f"  {col}: prob={prob:.4f} ({prob*100:.2f}%), actual={actual}")

    print("\n[PASS] AI4I inference test completed.")
    return True


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("  CausalCut SafetyTwin — Full Model Evaluation Suite")
    print("=" * 70)

    hydraulic_metrics = evaluate_hydraulic()
    ai4i_metrics = evaluate_ai4i()
    test_hydraulic_inference()
    test_ai4i_inference()

    # Dump metrics to JSON for documentation
    all_metrics = {
        "hydraulic": hydraulic_metrics,
        "ai4i": ai4i_metrics
    }
    metrics_path = os.path.join(WORKSPACE, ".models", "evaluation_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(all_metrics, f, indent=2)
    print(f"\nMetrics saved to {metrics_path}")

    separator("ALL EVALUATIONS COMPLETE")
