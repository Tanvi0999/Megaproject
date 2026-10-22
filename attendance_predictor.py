
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


# Locate saved models relative to this Python file
BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "saved_models_overall"

# Load trained models and hybrid settings
rf_model = joblib.load(MODEL_DIR / "overall_rf.pkl")
xgb_model = joblib.load(MODEL_DIR / "overall_xgb.pkl")
weights = joblib.load(MODEL_DIR / "overall_hybrid_weights.pkl")
features = joblib.load(MODEL_DIR / "overall_hybrid_features.pkl")

RF_WEIGHT = weights["rf_weight"]
XGB_WEIGHT = weights["xgb_weight"]
FEATURE_NAME = features[0]


def predict_attendance(input_df: pd.DataFrame) -> pd.DataFrame:
    """
    Predict next-year overall attendance.

    Required columns:
        Student_Name
        Roll_Number
        Overall_Attendance

    Returns student identifiers and predicted attendance.
    """

    required = [
        "Student_Name",
        "Roll_Number",
        "Overall_Attendance",
    ]

    missing = [col for col in required if col not in input_df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    if input_df.empty:
        raise ValueError("The input dataset is empty.")

    attendance = pd.to_numeric(
        input_df["Overall_Attendance"]
        .astype("string")
        .str.replace("%", "", regex=False)
        .str.strip(),
        errors="coerce",
    )

    if attendance.isna().any():
        raise ValueError(
            "Overall_Attendance contains missing or non-numeric values."
        )

    if not attendance.between(0, 100).all():
        raise ValueError(
            "Overall_Attendance must be between 0 and 100."
        )

    # Use the feature name expected by the trained models
    model_input = pd.DataFrame({
        FEATURE_NAME: attendance.to_numpy()
    })

    rf_predictions = rf_model.predict(model_input)
    xgb_predictions = xgb_model.predict(model_input)

    predictions = (
        RF_WEIGHT * rf_predictions
        + XGB_WEIGHT * xgb_predictions
    )

    predictions = np.clip(predictions, 0, 100)

    result = input_df[["Student_Name", "Roll_Number"]].copy()
    result["Predicted_Next_Year_Attendance"] = np.round(
        predictions, 2
    )

    return result


def predict_csv(input_path: str, output_path: str | None = None):
    """Read an uploaded CSV, predict attendance, and optionally save results."""

    input_df = pd.read_csv(input_path)
    results = predict_attendance(input_df)

    if output_path:
        results.to_csv(output_path, index=False)

    return results
