Hi! I've completed the hybrid ML model for overall attendance prediction using Random Forest + XGBoost.

For backend integration, please use:

- `attendance_predictor.py`
- `saved_models_overall/` (all 4 `.pkl` files)
- Required Python libraries: pandas, numpy, joblib, scikit-learn, xgboost

Import the prediction function using:
`from attendance_predictor import predict_attendance`

Pass the uploaded attendance CSV as a Pandas DataFrame with columns `Student_Name`, `Roll_Number`, and `Overall_Attendance`.

The function returns student names, roll numbers, and predicted next-year attendance. Please connect it to a backend API and send the prediction results to the frontend for display.

Keep the Python file and model folder together in the backend project, and don't retrain the model.
