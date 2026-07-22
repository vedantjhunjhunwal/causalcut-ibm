import joblib
import traceback
from pathlib import Path

path = Path(".models/XGB Classifier/model_1&2.joblib")
try:
    data = joblib.load(path)
    print("TYPE:", type(data))
    if isinstance(data, dict):
        print("KEYS:", data.keys())
        print("SCALER:", type(data.get("scaler")))
        print("MODEL:", type(data.get("model")))
    else:
        print("Not a dict")
except Exception as e:
    print("ERROR LOADING:")
    traceback.print_exc()
