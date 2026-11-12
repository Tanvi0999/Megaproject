import math
from io import BytesIO

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from app.database import SessionLocal
from app.models import (
    ImportJob,
    MarkPrediction,
    SGPIPrediction,
    Student,
)
from model_integration.predict import predict_from_excel
from academic_prediction_pipeline_v6_updated import (
    normalize_prn,
    mask_prn,
    get_academic_year,
)


def make_json_safe(value):
    if isinstance(value, dict):
        return {
            str(key): make_json_safe(val)
            for key, val in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            make_json_safe(item)
            for item in value
        ]

    if isinstance(value, np.ndarray):
        return [
            make_json_safe(item)
            for item in value.tolist()
        ]

    if isinstance(value, np.generic):
        value = value.item()

        if isinstance(value, float) and not math.isfinite(value):
            return None

        return value

    if isinstance(value, float) and not math.isfinite(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, pd.DataFrame):
        return make_json_safe(
            value.to_dict(orient="records")
        )

    return value


def build_prn_mask_mapping(
    workbook_bytes: bytes,
) -> dict[str, str]:
    """
    Build:

        Masked_ID -> normalized PRN

    using the exact same normalize_prn() and mask_prn()
    functions used by the ML pipeline.
    """

    workbook = load_workbook(
        BytesIO(workbook_bytes),
        read_only=True,
        data_only=True,
    )

    mapping = {}

    try:
        for ws in workbook.worksheets:

            for row in ws.iter_rows(values_only=True):

                for value in row:

                    prn = normalize_prn(value)

                    if not prn:
                        continue

                    masked_id = mask_prn(prn)

                    mapping[masked_id] = prn

    finally:
        workbook.close()

    return mapping


def generate_mark_predictions(
    workbook_bytes: bytes,
    workbook_name: str,
    target_subjects: list[dict],
) -> dict:

    if not workbook_bytes:
        raise ValueError("Uploaded Excel file is empty.")

    if not workbook_name:
        raise ValueError("Workbook filename is required.")

    if not target_subjects:
        raise ValueError("At least one target subject is required.")

    db = SessionLocal()

    import_job = None

    try:
        # ========================================================
        # 1. CREATE IMPORT JOB
        # ========================================================

        import_job = ImportJob(
            uploaded_by_user_id=None,
            file_name=workbook_name,
            file_type="xlsx",
            status="processing",
            total_rows=0,
            successful_rows=0,
            failed_rows=0,
            error_summary={},
        )

        db.add(import_job)
        db.commit()
        db.refresh(import_job)

        # ========================================================
        # 2. RUN EXISTING ML PIPELINE
        # ========================================================

        result = predict_from_excel(
            workbook_bytes=workbook_bytes,
            workbook_name=workbook_name,
            target_subjects=target_subjects,
        )

        subject_predictions = result.get(
            "subject_predictions"
        )

        sgpi_predictions = result.get(
            "sgpi_predictions"
        )

        # ========================================================
        # 3. CONVERT DATAFRAMES TO RECORDS
        # ========================================================

        if hasattr(subject_predictions, "to_dict"):
            subject_predictions = (
                subject_predictions.to_dict(
                    orient="records"
                )
            )

        if hasattr(sgpi_predictions, "to_dict"):
            sgpi_predictions = (
                sgpi_predictions.to_dict(
                    orient="records"
                )
            )

        subject_predictions = (
            subject_predictions or []
        )

        sgpi_predictions = (
            sgpi_predictions or []
        )

        # ========================================================
        # 4. BUILD MASKED_ID -> PRN MAPPING
        # ========================================================

        prn_mapping = build_prn_mask_mapping(
            workbook_bytes
        )

        # ========================================================
        # 5. FIND STUDENTS IN DATABASE
        # ========================================================

        masked_ids = set()

        for row in subject_predictions:
            if row.get("Masked_ID"):
                masked_ids.add(
                    str(row["Masked_ID"])
                )

        for row in sgpi_predictions:
            if row.get("Masked_ID"):
                masked_ids.add(
                    str(row["Masked_ID"])
                )

        student_mapping = {}

        for masked_id in masked_ids:

            prn = prn_mapping.get(masked_id)

            if not prn:
                continue

            student = (
                db.query(Student)
                .filter(Student.prn == prn)
                .first()
            )

            if student:
                student_mapping[masked_id] = student

        # ========================================================
        # 6. SAVE MARK PREDICTIONS
        # ========================================================

        successful_rows = 0
        failed_rows = 0
        errors = []

        for row in subject_predictions:

            masked_id = str(
                row.get("Masked_ID")
            )

            student = student_mapping.get(
                masked_id
            )

            if not student:

                failed_rows += 1

                errors.append({
                    "type": "student_mapping",
                    "masked_id": masked_id,
                    "message": (
                        "No student found for "
                        "the PRN associated with this Masked_ID."
                    ),
                })

                continue

            prediction = MarkPrediction(
                import_job_id=import_job.import_job_id,
                student_id=student.student_id,
                masked_id=masked_id,
                branch=str(
                    row.get("Branch", "")
                ),
                previous_semester=int(
                    row["Previous_Semester"]
                ),
                predicted_semester=int(
                    row["Predicted_Semester"]
                ),
                subject_code=str(
                    row["Subject_Code"]
                ),
                subject_name=str(
                    row["Subject_Name"]
                ),
                max_marks=float(
                    row["Max_Marks"]
                ),
                min_marks=(
                    float(row["Min_Marks"])
                    if row.get("Min_Marks") is not None
                    else None
                ),
                predicted_percentage=float(
                    row["Predicted_Percentage"]
                ),
                predicted_marks=(
                    float(row["Predicted_Marks"])
                    if row.get("Predicted_Marks") is not None
                    else None
                ),
                predicted_rf_percentage=(
                    float(
                        row["Predicted_RF_Percentage"]
                    )
                    if row.get(
                        "Predicted_RF_Percentage"
                    ) is not None
                    else None
                ),
                predicted_xgboost_percentage=(
                    float(
                        row["Predicted_XGBoost_Percentage"]
                    )
                    if row.get(
                        "Predicted_XGBoost_Percentage"
                    ) is not None
                    else None
                ),
                prediction_status=str(
                    row["Prediction_Status"]
                ),
                code_seen_in_branch_training=(
                    bool(
                        row[
                            "Code_Seen_In_Branch_Training"
                        ]
                    )
                    if row.get(
                        "Code_Seen_In_Branch_Training"
                    ) is not None
                    else None
                ),
                confidence_note=row.get(
                    "Confidence_Note"
                ),
                max_marks_status=row.get(
                    "Max_Marks_Status"
                ),
            )

            db.add(prediction)
            successful_rows += 1

        # ========================================================
        # 7. SAVE SGPI PREDICTIONS
        # ========================================================

        for row in sgpi_predictions:

            masked_id = str(
                row.get("Masked_ID")
            )

            student = student_mapping.get(
                masked_id
            )

            if not student:

                failed_rows += 1

                errors.append({
                    "type": "student_mapping",
                    "masked_id": masked_id,
                    "message": (
                        "No student found for "
                        "the PRN associated with this Masked_ID."
                    ),
                })

                continue

            prediction = SGPIPrediction(
                import_job_id=import_job.import_job_id,
                student_id=student.student_id,
                masked_id=masked_id,
                branch=str(
                    row.get("Branch", "")
                ),
                previous_semester=int(
                    row["Previous_Semester"]
                ),
                predicted_semester=int(
                    row["Predicted_Semester"]
                ),
                previous_sgpi=(
                    float(row["Previous_SGPI"])
                    if row.get("Previous_SGPI") is not None
                    else None
                ),
                predicted_sgpi=float(
                    row["Predicted_SGPI"]
                ),
                prediction_method=row.get(
                    "Prediction_Method"
                ),
            )

            db.add(prediction)
            successful_rows += 1

        # ========================================================
        # 8. UPDATE IMPORT JOB
        # ========================================================

        total_rows = (
            len(subject_predictions)
            + len(sgpi_predictions)
        )

        import_job.total_rows = total_rows
        import_job.successful_rows = successful_rows
        import_job.failed_rows = failed_rows

        import_job.error_summary = {
            "errors": errors,
            "students_mapped": len(
                student_mapping
            ),
            "masked_ids_found": len(masked_ids),
        }

        if failed_rows == 0:
            import_job.status = "completed"
        else:
            import_job.status = "completed_with_errors"

        from datetime import datetime, timezone

        import_job.completed_at = datetime.now(
            timezone.utc
        )

        db.commit()

        # ========================================================
        # 9. PRESERVE EXISTING API RESPONSE
        # ========================================================

        result["subject_predictions"] = (
            subject_predictions
        )

        result["sgpi_predictions"] = (
            sgpi_predictions
        )

        result["import_job_id"] = (
            import_job.import_job_id
        )

        result["database_persistence"] = {
            "status": import_job.status,
            "total_rows": total_rows,
            "successful_rows": successful_rows,
            "failed_rows": failed_rows,
            "students_mapped": len(
                student_mapping
            ),
        }

        result = make_json_safe(result)

        return result

    except Exception:

        db.rollback()

        if import_job is not None:

            try:
                import_job.status = "failed"
                import_job.error_summary = {
                    "message": "Prediction persistence failed."
                }

                db.commit()

            except Exception:
                db.rollback()

        raise

    finally:
        db.close()