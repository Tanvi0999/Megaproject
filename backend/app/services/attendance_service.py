
import pandas as pd

from backend.app.services.attendance_predictor import predict_attendance


def generate_attendance_predictions(records: list[dict]) -> list[dict]:
    """
    Generate next-year attendance predictions for students.

    Each record must contain:
        Student_Name
        Roll_Number
        Overall_Attendance
    """
    if not records:
        raise ValueError("At least one student record is required.")

    input_df = pd.DataFrame(records)

    predictions_df = predict_attendance(input_df)

    # Convert pandas/NumPy values into standard Python values
    # so FastAPI can serialize the response as JSON.
    return predictions_df.to_dict(orient="records")
