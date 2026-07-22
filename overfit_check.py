import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler, LabelEncoder
from sklearn.model_selection import cross_validate, StratifiedKFold
import os

WORKSPACE = r"c:\Users\Niranjan\Desktop\ET AI HACK\et-ai-Hackathon-"

# Hydraulic
print("=== HYDRAULIC: Train vs Test F1 (5-Fold CV) ===")
df = pd.read_csv(os.path.join(WORKSPACE, ".datasets", "hydraulic", "hydraulic_features.csv"))
tcols = ["Cooler_Condition","Valve_Condition","Pump_Leakage","Accumulator_Pressure","Stable_Flag"]
X = df.drop(columns=tcols)
print(f"Dataset: {X.shape[0]} samples, {X.shape[1]} features\n")

for col in tcols:
    le = LabelEncoder()
    y = le.fit_transform(df[col])
    nc = len(le.classes_)
    obj = "multiclass" if nc > 2 else "binary"
    p = Pipeline([("s", MinMaxScaler(feature_range=(-1,1))),
                  ("c", lgb.LGBMClassifier(objective=obj, num_class=nc if nc>2 else 1,
                                           n_jobs=1, random_state=42, verbosity=-1))])
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    r = cross_validate(p, X, y, cv=cv, scoring={"f1": "f1_macro"}, return_train_score=True, n_jobs=-1)
    tr = np.mean(r["train_f1"])
    te = np.mean(r["test_f1"])
    gap = tr - te
    flag = "OVERFIT" if gap > 0.05 else "OK"
    print(f"{col}: Train={tr:.4f}  Test={te:.4f}  Gap={gap:.4f}  [{flag}]")

# AI4I
print("\n=== AI4I: Train vs Test F1 (5-Fold CV) ===")
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
df2 = pd.read_csv(os.path.join(WORKSPACE, ".datasets", "ai4i", "ai4i_processed.csv"))
tcols2 = ["Machine_failure","TWF","HDF","PWF","OSF","RNF"]
X2 = df2.drop(columns=tcols2)
pre = ColumnTransformer([("num", MinMaxScaler(feature_range=(-1,1)),
                          ["Air_temperature","Process_temperature","Rotational_speed","Torque","Tool_wear"]),
                         ("cat", OneHotEncoder(handle_unknown="ignore"), ["Type"])])
print(f"Dataset: {X2.shape[0]} samples, {X2.shape[1]} features\n")

for col in tcols2:
    y = df2[col].values
    p = Pipeline([("pre", pre), ("c", lgb.LGBMClassifier(objective="binary", class_weight="balanced",
                                                          n_jobs=1, random_state=42, verbosity=-1))])
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    r = cross_validate(p, X2, y, cv=cv, scoring={"f1": "f1_macro"}, return_train_score=True, n_jobs=-1)
    tr = np.mean(r["train_f1"])
    te = np.mean(r["test_f1"])
    gap = tr - te
    flag = "OVERFIT" if gap > 0.05 else "OK"
    print(f"{col}: Train={tr:.4f}  Test={te:.4f}  Gap={gap:.4f}  [{flag}]")
