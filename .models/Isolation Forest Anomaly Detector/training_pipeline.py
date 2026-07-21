import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

# ==========================================
# 1. DATA INGESTION & FEATURE EXTRACTION
# ==========================================
# Load the dataset
df = pd.read_csv("/content/gas_sensors_drift.csv")

# Identify feature columns (all columns except metadata and labels)
metadata_cols = ["label", "source_file"]
feature_cols = [col for col in df.columns if col not in metadata_cols]

# Chronological Split: Pool Batches 1 and 2 to form the "Early-Life Baseline" (~1,689 samples)
# This prevents learning irreversible chemical drift while providing ample variance for Isolation Forest.
baseline_batches = ["batch1.dat", "batch2.dat"]
train_mask = df["source_file"].isin(baseline_batches)

X_train = df.loc[train_mask, feature_cols]
X_eval = df.loc[~train_mask, feature_cols]

print(
    f"Training baseline model on {len(X_train)} samples (Batches 1 & 2)..."
)
print(
    f"Evaluating drift progression across {len(X_eval)} samples (Batches 3-10)...\n"
)

# ==========================================
# 2. PIPELINE CONSTRUCTION & TRAINING
# ==========================================
# Build the unified scaler -> model pipeline
# MinMaxScaler fits strictly on X_train and embeds exact min/max bounds into the pipeline
drift_pipeline = Pipeline(
    [
        ("scaler", MinMaxScaler()),
        (
            "iso_forest",
            IsolationForest(
                n_estimators=200,
                max_samples="auto",  # Subsamples min(256, n_samples) per tree
                contamination=0.03,  # Expected noise rate during early-life baseline
                max_features=1.0,
                bootstrap=False,
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ]
)

# Fit the entire pipeline strictly on the baseline data
drift_pipeline.fit(X_train)

# ==========================================
# 3. MODEL PERSISTENCE
# ==========================================
model_filename = "gas_sensor_isoforest_pipeline.joblib"
joblib.dump(drift_pipeline, model_filename)
print(
    f"[SUCCESS] Exported self-contained inference artifact to: {model_filename}\n"
)

# ==========================================
# 4. INFERENCE & METRIC EVALUATION
# ==========================================
# Load the exported pipeline to simulate live production inference
deployed_model = joblib.load(model_filename)

# ------------------------------------------------------------------
# A. BATCH-WISE ANOMALY / DRIFT PROGRESSION REPORT
# ------------------------------------------------------------------
# In a healthy baseline model, anomaly rates start low (~3%) and rise
# steadily as physical sensor degradation accumulates over the 36-month timeline.
print("=" * 65)
print("CHRONOLOGICAL BATCH-WISE DRIFT PROGRESSION")
print("=" * 65)
print(
    f"{'Batch Name':<15} {'Total Samples':<15} {'Anomalies Flagged':<20} {'Drift Rate (%)':<15}"
)
print("-" * 65)

# Sort batches chronologically (extracting integer from 'batchX.dat')
sorted_batches = sorted(
    df["source_file"].unique(),
    key=lambda x: int(x.replace("batch", "").replace(".dat", "")),
)

for batch_name in sorted_batches:
    batch_mask = df["source_file"] == batch_name
    X_batch = df.loc[batch_mask, feature_cols]

    # Predict outputs: 1 for inlier (normal), -1 for outlier (anomaly/drift)
    # The internal MinMaxScaler automatically scales X_batch using Batch 1&2 bounds
    preds = deployed_model.predict(X_batch)
    anomalies_count = np.sum(preds == -1)
    total_samples = len(X_batch)
    drift_rate = (anomalies_count / total_samples) * 100

    # Mark baseline batches in the console output
    tag = " (Baseline)" if batch_name in baseline_batches else ""
    print(
        f"{batch_name + tag:<15} {total_samples:<15} {anomalies_count:<20} {drift_rate:<15.2f}"
    )

print("-" * 65 + "\n")

# ------------------------------------------------------------------
# B. DISCRIMINATION ACCURACY METRICS (Baseline vs. Severe Drift)
# ------------------------------------------------------------------
# To compute standard supervised metrics, we construct a binary benchmark:
# Ground Truth 0 (Normal) = Batches 1 & 2
# Ground Truth 1 (Severe Drift) = Batches 8, 9, and 10
print("=" * 65)
print(
    "DISCRIMINATION ACCURACY: BASELINE (Batches 1-2) VS SEVERE DRIFT (Batches 8-10)"
)
print("=" * 65)

severe_drift_batches = ["batch8.dat", "batch9.dat", "batch10.dat"]
benchmark_mask = df["source_file"].isin(
    baseline_batches + severe_drift_batches
)
X_benchmark = df.loc[benchmark_mask, feature_cols]

# Create ground truth binary target vector
y_true_binary = np.where(
    df.loc[benchmark_mask, "source_file"].isin(baseline_batches), 0, 1
)

# Predict using the deployed pipeline and map Isolation Forest outputs:
# -1 (Anomaly) -> 1 (Drift detected)
#  1 (Inlier)  -> 0 (Normal sensor)
raw_preds = deployed_model.predict(X_benchmark)
y_pred_binary = np.where(raw_preds == -1, 1, 0)

# Continuous anomaly scores for ROC-AUC calculation
# decision_function returns lower scores for anomalies, so we negate (-scores)
# to ensure higher values correspond to higher probability of drift.
continuous_drift_scores = -deployed_model.decision_function(X_benchmark)
roc_auc = roc_auc_score(y_true_binary, continuous_drift_scores)

print(f"ROC-AUC Score: {roc_auc:.4f}\n")
print("Classification Report:")
print(
    classification_report(
        y_true_binary,
        y_pred_binary,
        target_names=[
            "Normal (Batches 1-2)",
            "Severe Drift (Batches 8-10)",
        ],
    )
)

print("Confusion Matrix:")
cm = confusion_matrix(y_true_binary, y_pred_binary)
print(f"True Negatives  (Correctly Identified Normal): {cm[0, 0]:<6}")
print(
    f"False Positives (Baseline False Alarms):       {cm[0, 1]:<6}"
)
print(
    f"False Negatives (Missed Severe Drift):         {cm[1, 0]:<6}"
)
print(f"True Positives  (Correctly Caught Drift):      {cm[1, 1]:<6}")
print("=" * 65)
