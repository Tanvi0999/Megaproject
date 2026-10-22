
import joblib
import pandas as pd
from pathlib import Path

# --------------------------------------------------
# 1. Set model directory
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "saved_models_overall"

# --------------------------------------------------
# 2. Load trained models and hybrid weights
# --------------------------------------------------

rf_model = joblib.load(MODEL_DIR / "overall_rf.pkl")
xgb_model = joblib.load(MODEL_DIR / "overall_xgb.pkl")

weights = joblib.load(
    MODEL_DIR / "overall_hybrid_weights.pkl"
)

features = joblib.load(
    MODEL_DIR / "overall_hybrid_features.pkl"
)

RF_WEIGHT = weights["rf_weight"]
XGB_WEIGHT = weights["xgb_weight"]
FEATURE_NAME = features[0]


# --------------------------------------------------
# 3. Predict next-year attendance for multiple students
# --------------------------------------------------

def predict_attendance(input_df):
    """
    Predict next-year overall attendance using a
    Random Forest + XGBoost weighted hybrid model.

    Required input columns:
        Student_Name
        Roll_Number
        Overall_Attendance

    Overall_Attendance represents previous-year
    overall attendance as a percentage.

    Returns:
        DataFrame containing student details and
        predicted next-year overall attendance.
    """

    # Check input type
    if not isinstance(input_df, pd.DataFrame):
        raise TypeError("Input must be a Pandas DataFrame.")

    # Required columns
    required_columns = [
        "Student_Name",
        "Roll_Number",
        "Overall_Attendance"
    ]

    # Check missing columns
    missing_columns = [
        column
        for column in required_columns
        if column not in input_df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    # Check for empty input
    if input_df.empty:
        raise ValueError("Input DataFrame is empty.")

    # Make a copy to avoid changing the original data
    input_df = input_df.copy()

    # Validate student details
    if input_df["Student_Name"].isna().any():
        raise ValueError("Student_Name cannot be empty.")

    if input_df["Roll_Number"].isna().any():
        raise ValueError("Roll_Number cannot be empty.")

    # Convert attendance to numeric values
    input_df["Overall_Attendance"] = pd.to_numeric(
        input_df["Overall_Attendance"],
        errors="coerce"
    )

    # Validate attendance values
    if input_df["Overall_Attendance"].isna().any():
        raise ValueError(
            "Attendance must contain valid numeric values."
        )

    if not input_df["Overall_Attendance"].between(0, 100).all():
        raise ValueError(
            "Attendance must be between 0 and 100."
        )

    # --------------------------------------------------
    # 4. Prepare model input
    # --------------------------------------------------

    model_input = input_df[
        ["Overall_Attendance"]
    ].copy()

    # Use the feature name expected by the trained models
    model_input.columns = [FEATURE_NAME]

    # --------------------------------------------------
    # 5. Generate predictions from both models
    # --------------------------------------------------

    rf_predictions = rf_model.predict(model_input)

    xgb_predictions = xgb_model.predict(model_input)

    # --------------------------------------------------
    # 6. Combine predictions using hybrid weights
    # --------------------------------------------------

    hybrid_predictions = (
        RF_WEIGHT * rf_predictions
        + XGB_WEIGHT * xgb_predictions
    )

    # Keep attendance between 0 and 100
    hybrid_predictions = hybrid_predictions.clip(0, 100)

    # --------------------------------------------------
    # 7. Prepare final output
    # --------------------------------------------------

    results = input_df[
        ["Student_Name", "Roll_Number"]
    ].copy()

    results["Predicted_Next_Year_Attendance"] = (
        hybrid_predictions.round(2)
    )

    return results


# --------------------------------------------------
# 8. Predict directly from a CSV file (optional)
# --------------------------------------------------

def predict_csv(input_path, output_path=None):
    """
    Read student attendance from a CSV file,
    generate predictions, and optionally save results.
    """

    input_df = pd.read_csv(input_path)

    results = predict_attendance(input_df)

    if output_path is not None:
        results.to_csv(output_path, index=False)
        print(f"Predictions saved to: {output_path}")

    return results
