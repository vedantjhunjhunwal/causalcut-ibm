import joblib
import numpy as np
import xgboost as xgb
import sklearn
from datetime import datetime, timezone
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler
from sklearn.utils.class_weight import compute_class_weight
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold


def train_optimize_and_export_pipeline(
    X_train_raw: np.ndarray,
    y_train: np.ndarray,
    export_path: str,
    version_name: str,
    train_batches: list[int],
    class_names: list[str] | None = None,
):
    """
    Runs a RandomizedSearchCV over an XGBoost pipeline using sample weights,
    optimizes for macro F1-score, and exports a payload dictionary containing
    the fitted scaler, model, and metadata.

    Args:
        X_train_raw: Raw 128-dim feature array (unscaled) for whichever
            batch pool this model version is trained on.
        y_train: Integer encoded target labels (0 to 5).
        export_path: Destination path for the serialized artifact.
        version_name: A custom version string (e.g., "xgb-gas-A-1.0").
        train_batches: Which batch numbers went into this training pool,
            e.g. [1, 2]. Stored in the artifact for provenance/debugging
            across the model bank — don't skip this.
        class_names: Ordered list mapping int label -> gas name, e.g.
            ["Ethanol", "Ethylene", ...]. Pass this explicitly rather than
            assuming an order; a wrong guess here fails silently at
            inference time, not at training time.
    """
    # 1. Dynamically compute class weights based on the training labels
    classes = np.unique(y_train)
    weights = compute_class_weight(class_weight='balanced', classes=classes, y=y_train)
    class_weights_dict = dict(zip(classes, weights))
    sample_weights = np.vectorize(class_weights_dict.get)(y_train)

    # 2. Define the baseline sequential pipeline steps
    #    NOTE: n_jobs=1 here on purpose — see param_distributions comment below.
    base_pipeline = Pipeline([
        ('scaler', MinMaxScaler(feature_range=(-1, 1))),
        ('classifier', xgb.XGBClassifier(
            objective='multi:softprob',
            num_class=len(classes),
            eval_metric='mlogloss',
            n_jobs=1,
            random_state=42
        ))
    ])

    # 3. Hyperparameter search space
    #    FIX: the original had `'classifier__n_estimators':,` and
    #    `'classifier__max_depth':,` — empty values after the colon, which
    #    is a hard SyntaxError in Python. This never ran.
    param_distributions = {
        'classifier__n_estimators': [100, 200, 300, 400, 500],
        'classifier__max_depth': [3, 4, 5, 6, 7, 8],
        'classifier__learning_rate': [0.01, 0.05, 0.1, 0.2],
        'classifier__subsample': [0.6, 0.7, 0.8, 0.9],
        'classifier__colsample_bytree': [0.6, 0.7, 0.8, 0.9],
        'classifier__min_child_weight': [1, 3, 5]
    }

    # 4. Cross-validation strategy.
    #    This CV loop is your held-out evaluation — no separate manual
    #    split needed. StratifiedKFold keeps Toluene's ~79 samples spread
    #    across folds instead of risking a fold with almost none.
    cv_strategy = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    random_search = RandomizedSearchCV(
        estimator=base_pipeline,
        param_distributions=param_distributions,
        n_iter=15,
        scoring='f1_macro',
        cv=cv_strategy,
        random_state=42,
        n_jobs=-1,   # parallelism now lives here, not inside XGBoost
        verbose=1,
        refit=True,  # after CV picks best params, refits on the FULL pool
    )

    # 5. Route sample weights to the classifier's fit method.
    #    sklearn automatically row-slices this per CV fold to match each
    #    fold's train indices — it does NOT apply the full-pool weights
    #    to a subset, so this is safe as written.
    fit_params = {'classifier__sample_weight': sample_weights}

    print(f"Initiating RandomizedSearchCV for version [{version_name}] "
          f"on batches {train_batches}...")
    random_search.fit(X_train_raw, y_train, **fit_params)

    print("\n--- Optimization Complete ---")
    print(f"Best Macro F1-Score (mean over 5 folds): {random_search.best_score_:.4f}")
    print(f"Best Params: {random_search.best_params_}")

    # 6. Extract the individual named steps from the refit-on-full-pool estimator
    best_pipeline = random_search.best_estimator_
    fitted_scaler = best_pipeline.named_steps['scaler']
    fitted_model = best_pipeline.named_steps['classifier']

    if class_names is None:
        print("WARNING: class_names not provided — inference code downstream "
              "will have to assume the label order. Strongly recommend passing it.")

    # 7. Construct the artifact payload — includes provenance and library
    #    pins so a version mismatch fails loudly at load time instead of
    #    surfacing as a silent bad prediction or a pickle error later.
    artifact_payload = {
        "version": version_name,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "train_batches": train_batches,
        "n_train_samples": int(len(y_train)),
        "class_names": class_names,
        "cv_best_score_macro_f1": float(random_search.best_score_),
        "cv_best_params": random_search.best_params_,
        "library_versions": {
            "xgboost": xgb.__version__,
            "sklearn": sklearn.__version__,
        },
        "scaler": fitted_scaler,
        "model": fitted_model,
    }

    # 8. Serialize
    joblib.dump(artifact_payload, export_path)
    print(f"\nArtifact successfully saved to: {export_path}")

    return artifact_payload


# Example execution:
train_optimize_and_export_pipeline(
    X_train_raw=X_train_batch1,
    y_train=y_train_batch1,
    export_path="model_1&2.joblib",
    version_name="xgb-gas-1&2-1.0",
    train_batches=[1, 2],
    class_names=["Ethanol", "Ethylene", "Ammonia", "Acetaldehyde", "Acetone", "Toluene"],
)
