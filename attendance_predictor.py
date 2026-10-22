
import joblib
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "saved_models"

model = joblib.load(MODEL_DIR / "attendance_model.pkl")
feature_names = joblib.load(
    MODEL_DIR / "attendance_features.pkl"
)


def predict_attendance(student_features):
    """
    student_features: dictionary containing all required
    feature names and their numerical values.
    """
    missing = [
        name for name in feature_names
        if name not in student_features
    ]

    if missing:
        raise ValueError(
            f"Missing required features: {missing}"
        )

    input_df = pd.DataFrame(
        [[student_features[name] for name in feature_names]],
        columns=feature_names
    )

    prediction = float(model.predict(input_df)[0])

    # Attendance is expressed as a percentage.
    prediction = max(0.0, min(100.0, prediction))

    return round(prediction, 2)
