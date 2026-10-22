
import joblib
from pathlib import Path
from attendance_predictor import predict_attendance

model_dir = Path(__file__).resolve().parent / "saved_models"

feature_names = joblib.load(
    model_dir / "attendance_features.pkl"
)

sample_student = {
    feature: 0 for feature in feature_names
}

prediction = predict_attendance(sample_student)

print("Prediction function works!")
print("Predicted attendance:", prediction, "%")
