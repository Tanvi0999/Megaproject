
import json
import sys
from pathlib import Path

import joblib
import pandas as pd

# --------------------------------------------------
# PROJECT PATHS
# --------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = Path(__file__).resolve().parent

MODEL_DIR = INTEGRATION_DIR / "saved_models_academic"
REGISTRY_PATH = INTEGRATION_DIR / "subject_code_registry.json"
MASK_KEY_PATH = ROOT / "student_mask.key"

PIPELINE_PATH = ROOT / "academic_prediction_pipeline_v6_updated.py"

# --------------------------------------------------
# CHECK REQUIRED FILES BEFORE IMPORTING PIPELINE
# --------------------------------------------------

if not PIPELINE_PATH.exists():
    raise FileNotFoundError(
        f"Original V6 pipeline not found: {PIPELINE_PATH}"
    )

if not MASK_KEY_PATH.exists():
    raise FileNotFoundError(
        "student_mask.key is missing. "
        "The original masking key must remain in the project root."
    )

for filename in [
    "subject_hybrid_model.joblib",
    "sgpi_hybrid_model.joblib"
]:
    if not (MODEL_DIR / filename).exists():
        raise FileNotFoundError(
            f"Saved model missing: {MODEL_DIR / filename}"
        )

if not REGISTRY_PATH.exists():
    raise FileNotFoundError(
        f"Subject registry missing: {REGISTRY_PATH}"
    )

# --------------------------------------------------
# IMPORT ORIGINAL V6 PIPELINE
# --------------------------------------------------

sys.path.insert(0, str(ROOT))

import academic_prediction_pipeline_v6_updated as pipeline

# --------------------------------------------------
# LOAD EXISTING MODELS
# --------------------------------------------------

subject_bundle = joblib.load(
    MODEL_DIR / "subject_hybrid_model.joblib"
)

sgpi_bundle = joblib.load(
    MODEL_DIR / "sgpi_hybrid_model.joblib"
)

# --------------------------------------------------
# LOAD SUBJECT REGISTRY
# --------------------------------------------------

with open(REGISTRY_PATH, "r", encoding="utf-8") as file:
    subject_registry = json.load(file)

# The prediction function expects training_subjects
# containing Branch and Target_Subject_Code.
training_subjects = pd.DataFrame([
    {
        "Branch": branch,
        "Target_Subject_Code": code
    }
    for branch, codes in subject_registry.items()
    for code in codes
])

# --------------------------------------------------
# MAIN PREDICTION FUNCTION
# --------------------------------------------------

def predict_from_excel(
    workbook_bytes,
    workbook_name,
    target_subjects
):
    """
    Accepts:
        workbook_bytes: Uploaded Excel file bytes
        workbook_name: Original Excel filename
        target_subjects: List of target-subject dictionaries

    Returns:
        Subject predictions
        SGPI predictions
        Extraction logs
        Duplicate validation
    """

    if not isinstance(workbook_bytes, bytes) or not workbook_bytes:
        raise ValueError("Uploaded Excel file is empty.")

    if not target_subjects:
        raise ValueError("At least one target subject is required.")

    # Convert target subjects into a DataFrame
    target_df = pd.DataFrame(target_subjects)

    required_columns = [
        "Branch",
        "Semester",
        "Subject_Code",
        "Subject_Name",
        "Max_Marks",
        "Min_Marks"
    ]

    missing_columns = [
        col for col in required_columns
        if col not in target_df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing target-subject fields: {missing_columns}"
        )

    # Normalize target subject values
    target_df["Branch"] = (
        target_df["Branch"]
        .apply(pipeline.normalize_branch)
    )

    target_df["Subject_Code"] = (
        target_df["Subject_Code"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    target_df["Subject_Name"] = (
        target_df["Subject_Name"]
        .astype(str)
        .str.strip()
    )

    target_df["Max_Marks"] = pd.to_numeric(
        target_df["Max_Marks"],
        errors="coerce"
    )

    target_df["Min_Marks"] = pd.to_numeric(
        target_df["Min_Marks"],
        errors="coerce"
    )

    target_df["Semester"] = pd.to_numeric(
        target_df["Semester"],
        errors="coerce"
    )

    if target_df["Branch"].eq("").any():
        raise ValueError("Target subject contains an empty branch.")

    if target_df["Max_Marks"].isna().any() or (
        target_df["Max_Marks"] <= 0
    ).any():
        raise ValueError("Max_Marks must be greater than zero.")

    if target_df["Subject_Code"].eq("").any():
        raise ValueError("Subject_Code cannot be empty.")

    if target_df["Subject_Name"].eq("").any():
        raise ValueError("Subject_Name cannot be empty.")

    invalid_semesters = (
        target_df["Semester"].notna()
        & ~target_df["Semester"].between(1, 8)
    )

    if invalid_semesters.any():
        raise ValueError("Semester must be between 1 and 8.")

    invalid_min_marks = (
        target_df["Min_Marks"].notna()
        & (target_df["Min_Marks"] > target_df["Max_Marks"])
    )

    if invalid_min_marks.any():
        raise ValueError("Min_Marks cannot exceed Max_Marks.")

    # --------------------------------------------------
    # EXTRACT UPLOADED EXCEL
    # --------------------------------------------------

    academic_year = pipeline.get_academic_year(
        workbook_name
    )

    subject_rows, sgpi_rows, logs = (
        pipeline.extract_workbook_bytes(
            workbook_bytes,
            workbook_name,
            academic_year
        )
    )

    user_subjects = pd.DataFrame(subject_rows)
    user_sgpi = pd.DataFrame(sgpi_rows)

    # --------------------------------------------------
    # CLEAN AND FILTER
    # --------------------------------------------------

    user_subjects, user_sgpi = pipeline.clean_data(
        user_subjects,
        user_sgpi
    )

    user_subjects, user_sgpi = (
        pipeline.filter_supported_branches(
            user_subjects,
            user_sgpi
        )
    )

    # --------------------------------------------------
    # PREDICTION
    # --------------------------------------------------

    subject_predictions, sgpi_predictions = (
        pipeline.predict_user_ledgers(
            user_subjects,
            user_sgpi,
            subject_bundle,
            sgpi_bundle,
            target_df,
            training_subjects
        )
    )

    # --------------------------------------------------
    # DUPLICATE VALIDATION
    # --------------------------------------------------

    duplicate_validation = pipeline.validate_duplicates(
        subject_predictions,
        sgpi_predictions
    )

    return {
        "academic_year": academic_year,
        "extraction_logs": logs,
        "subject_predictions": subject_predictions,
        "sgpi_predictions": sgpi_predictions,
        "duplicate_validation": duplicate_validation
    }
