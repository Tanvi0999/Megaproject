
from predict import (
    subject_bundle,
    sgpi_bundle,
    subject_registry,
    training_subjects,
    predict_from_excel
)

print("\n========== MODEL INTEGRATION TEST ==========\n")

# 1. Check subject model
print("1. Subject model loaded successfully")
print("   Task:", subject_bundle.get("task"))
print("   Target:", subject_bundle.get("target"))
print("   RF weight:", subject_bundle.get("rf_weight"))
print("   XGBoost weight:", subject_bundle.get("xgb_weight"))
print("   Features:", len(subject_bundle.get("feature_columns", [])))

# 2. Check SGPI model
print("\n2. SGPI model loaded successfully")
print("   Task:", sgpi_bundle.get("task"))
print("   Target:", sgpi_bundle.get("target"))
print("   RF weight:", sgpi_bundle.get("rf_weight"))
print("   XGBoost weight:", sgpi_bundle.get("xgb_weight"))
print("   Features:", len(sgpi_bundle.get("feature_columns", [])))

# 3. Check subject registry
print("\n3. Subject registry loaded successfully")
print("   Branches:", len(subject_registry))
print("   Registry entries:", len(training_subjects))

# 4. Check prediction function
print("\n4. Prediction function imported successfully")
print("   Function:", predict_from_excel.__name__)

print("\n========== ALL BASIC TESTS PASSED ==========")
