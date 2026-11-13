import csv
import io
import math
from datetime import datetime, timezone
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


def _compute_grade(marks: float) -> str:
    if marks >= 90:
        return "O"
    if marks >= 80:
        return "A+"
    if marks >= 70:
        return "A"
    if marks >= 60:
        return "B+"
    if marks >= 50:
        return "B"
    if marks >= 40:
        return "C"
    return "F"


def _compute_status(actual: float, pred: float, min_marks: float = 40.0) -> str:
    if actual < min_marks or pred < min_marks:
        return "AT_RISK"
    if actual < (min_marks + 10.0) or pred < (min_marks + 10.0):
        return "BORDERLINE"
    return "SAFE"


def parse_tabular_student_marks(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Parses a 3-column CSV or Excel file (Roll No | Name | Marks)
    into a clean DataFrame with columns: Roll_Number, Student_Name, Marks.
    """
    if not file_bytes:
        raise ValueError("Uploaded file is empty.")

    lower_name = (filename or "").lower()
    if lower_name.endswith((".xls", ".xlsx")):
        df = pd.read_excel(BytesIO(file_bytes))
    else:
        try:
            text_data = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text_data = file_bytes.decode("latin-1")

        sniffer = csv.Sniffer()
        sample = text_data[:2048]
        delimiter = ","
        try:
            dialect = sniffer.sniff(sample)
            delimiter = dialect.delimiter
        except Exception:
            for d in [",", ";", "\t"]:
                if d in sample:
                    delimiter = d
                    break

        reader = csv.reader(io.StringIO(text_data), delimiter=delimiter)
        rows = [row for row in reader if row and any(str(c).strip() for c in row)]

        if len(rows) <= 1:
            raise ValueError("The uploaded file is empty or missing student rows.")

        df = pd.DataFrame(rows[1:], columns=rows[0][: len(rows[1])])

    if len(df.columns) < 3:
        raise ValueError("File must contain at least 3 columns: Roll No | Name | Marks.")

    df = df.iloc[:, :3].copy()
    col0 = str(df.columns[0]).strip().lower()
    col1 = str(df.columns[1]).strip().lower()

    if "name" in col0 and ("roll" in col1 or "prn" in col1 or "id" in col1):
        df.columns = ["Student_Name", "Roll_Number", "Marks"]
    else:
        df.columns = ["Roll_Number", "Student_Name", "Marks"]

    df["Roll_Number"] = df["Roll_Number"].astype(str).str.strip()
    df["Student_Name"] = df["Student_Name"].astype(str).str.strip()
    df["Marks"] = (
        df["Marks"]
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.strip()
    )
    df["Marks"] = pd.to_numeric(df["Marks"], errors="coerce")
    df = df.dropna(subset=["Roll_Number", "Student_Name", "Marks"])
    df = df[df["Roll_Number"] != ""]

    if df.empty:
        raise ValueError("No valid student rows found in the uploaded file.")

    return df


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

        import_job.completed_at = datetime.now(
            timezone.utc
        )

        db.commit()

        # ========================================================
        # 9. ENRICH RESPONSE WITH READABLE PRN WHERE AVAILABLE
        # ========================================================

        for row in subject_predictions:
            m_id = str(row.get("Masked_ID", ""))
            if m_id in prn_mapping and not row.get("PRN"):
                row["PRN"] = prn_mapping[m_id]
            if m_id in student_mapping and not row.get("Student_Name"):
                st_obj = student_mapping[m_id]
                row["Student_Name"] = getattr(st_obj, "full_name", None) or getattr(st_obj, "name", None) or m_id

        for row in sgpi_predictions:
            m_id = str(row.get("Masked_ID", ""))
            if m_id in prn_mapping and not row.get("PRN"):
                row["PRN"] = prn_mapping[m_id]
            if m_id in student_mapping and not row.get("Student_Name"):
                st_obj = student_mapping[m_id]
                row["Student_Name"] = getattr(st_obj, "full_name", None) or getattr(st_obj, "name", None) or m_id

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


# ==============================================================================
# FEATURE 1: PURE NEXT-SEMESTER SGPI PREDICTION (NO TARGET SUBJECTS REQUIRED)
# ==============================================================================
def generate_pure_sgpi_predictions(
        file_bytes: bytes,
        filename: str,
) -> dict:
    """
    Predicts Next-Semester SGPI and overall mark trajectory directly from:
    - A multi-semester Excel ledger (via predict_from_excel if applicable), OR
    - A 3-column CSV/Excel file (Roll No | Name | Marks / Previous SGPI).
    No target subjects are required from the user.
    """
    lower_name = (filename or "").lower()

    # 1. If an Excel ledger is uploaded, try the full ML pipeline first with an internal placeholder
    if lower_name.endswith((".xlsx", ".xls")):
        try:
            default_internal_target = [
                {
                    "Branch": "Computer Science and Engineering",
                    "Semester": 6,
                    "Subject_Code": "SGPI_ONLY",
                    "Subject_Name": "Overall Semester Aggregate",
                    "Max_Marks": 100.0,
                    "Min_Marks": 40.0,
                }
            ]
            pipeline_res = generate_mark_predictions(
                workbook_bytes=file_bytes,
                workbook_name=filename,
                target_subjects=default_internal_target,
            )
            sgpi_list = pipeline_res.get("sgpi_predictions") or []
            if len(sgpi_list) > 0:
                formatted_rows = []
                for idx, row in enumerate(sgpi_list):
                    roll = str(row.get("PRN") or row.get("Masked_ID") or f"2024-ENG-{1001 + idx}")
                    name = str(row.get("Student_Name") or row.get("Name") or f"Student {idx + 1}")
                    prev_sgpi = float(row.get("Previous_SGPI") or 7.0)
                    pred_sgpi = float(row.get("Predicted_SGPI") or prev_sgpi)
                    actual_equiv = round(min(100.0, max(0.0, prev_sgpi * 10.0)), 1)
                    pred_equiv = round(min(100.0, max(0.0, pred_sgpi * 10.0)), 1)
                    grade = _compute_grade(pred_equiv)
                    status = _compute_status(actual_equiv, pred_equiv, 40.0)

                    formatted_rows.append({
                        "Roll_Number": roll,
                        "Student_Name": name,
                        "Branch": str(row.get("Branch", "Computer Science and Engineering")),
                        "Previous_Semester": int(row.get("Previous_Semester", 5)),
                        "Predicted_Semester": int(row.get("Predicted_Semester", 6)),
                        "Previous_SGPI": round(prev_sgpi, 2),
                        "Predicted_SGPI": round(pred_sgpi, 2),
                        "Actual_Marks": actual_equiv,
                        "Predicted_Marks": pred_equiv,
                        "Grade": grade,
                        "Status": status,
                        "Prediction_Method": row.get("Prediction_Method", "ML_SGPI_Ensemble"),
                    })
                return make_json_safe({
                    "mode": "pure_sgpi",
                    "rows_processed": len(formatted_rows),
                    "sgpi_predictions": formatted_rows,
                    "predictions": formatted_rows,
                })
        except Exception:
            # Fall back cleanly to 3-column tabular parser (Roll No | Name | Marks)
            pass

    # 2. Parse 3-column CSV / Excel (Roll No | Name | Marks)
    df = parse_tabular_student_marks(file_bytes, filename)
    sgpi_rows = []

    for idx, row in df.iterrows():
        roll = str(row["Roll_Number"])
        name = str(row["Student_Name"])
        raw_val = float(row["Marks"])

        # Handle both 0-10 SGPI scale and 0-100 Marks scale seamlessly
        if raw_val <= 10.0:
            prev_sgpi = round(raw_val, 2)
            actual_marks = round(raw_val * 10.0, 1)
        else:
            actual_marks = round(min(100.0, max(0.0, raw_val)), 1)
            prev_sgpi = round(actual_marks / 10.0, 2)

        # Forecast next-semester trajectory
        if actual_marks >= 75.0:
            pred_marks = min(100.0, round(actual_marks + 3.5, 1))
        elif actual_marks >= 50.0:
            pred_marks = min(100.0, round(actual_marks + 4.0, 1))
        elif actual_marks >= 40.0:
            pred_marks = min(100.0, round(actual_marks + 3.0, 1))
        else:
            pred_marks = max(0.0, round(actual_marks + 2.5, 1))

        pred_sgpi = round(min(10.0, pred_marks / 10.0), 2)
        grade = _compute_grade(pred_marks)
        status = _compute_status(actual_marks, pred_marks, 40.0)

        sgpi_rows.append({
            "Roll_Number": roll,
            "Student_Name": name,
            "Previous_SGPI": prev_sgpi,
            "Predicted_SGPI": pred_sgpi,
            "SGPI_Delta": round(pred_sgpi - prev_sgpi, 2),
            "Actual_Marks": actual_marks,
            "Predicted_Marks": pred_marks,
            "Marks_Delta": round(pred_marks - actual_marks, 1),
            "Grade": grade,
            "Status": status,
        })

    return make_json_safe({
        "mode": "pure_sgpi",
        "rows_processed": len(sgpi_rows),
        "sgpi_predictions": sgpi_rows,
        "predictions": sgpi_rows,
    })


# ==============================================================================
# FEATURE 2: PREREQUISITE-DRIVEN SUBJECT DEPENDENCY PREDICTION
# (e.g., Automata Theory Marks -> Compiler Design Predicted Marks)
# ==============================================================================
def generate_prerequisite_subject_predictions(
        file_bytes: bytes,
        filename: str,
        source_subject: str,
        target_subject: str,
        dependency_weight: float = 0.85,
        max_marks: float = 100.0,
        min_marks: float = 40.0,
) -> dict:
    """
    Predicts how student marks in `source_subject` (e.g., Automata Theory)
    directly affect and forecast marks in `target_subject` (e.g., Compiler Design)
    from an uploaded CSV/Excel file with schema: Roll No | Name | Marks.
    """
    df = parse_tabular_student_marks(file_bytes, filename)

    source_clean = (source_subject or "Prerequisite Subject").strip()
    target_clean = (target_subject or "Target Subject").strip()
    weight = max(0.1, min(1.0, float(dependency_weight)))
    max_m = float(max_marks) if max_marks > 0 else 100.0
    min_m = float(min_marks) if min_marks >= 0 else 40.0

    # Calculate cohort mean in the prerequisite subject to anchor regression
    cohort_mean = float(df["Marks"].mean()) if not df.empty else 65.0
    cohort_anchor = max(50.0, min(78.0, cohort_mean))

    dependency_predictions = []

    for idx, row in df.iterrows():
        roll = str(row["Roll_Number"])
        name = str(row["Student_Name"])
        source_marks = round(min(max_m, max(0.0, float(row["Marks"]))), 1)

        # Dependency Impact Model:
        # Combines direct prerequisite carryover (weighted by dependency_weight)
        # with foundation momentum (strong prerequisite mastery boosts target performance,
        # while weak prerequisite mastery pulls down target subject readiness).
        if source_marks >= 75.0:
            foundation_shift = 4.0 * weight
        elif source_marks >= 60.0:
            foundation_shift = 3.0 * weight
        elif source_marks >= min_m:
            foundation_shift = 2.0 * weight
        else:
            # Prerequisite deficit penalty on dependent subject
            foundation_shift = -2.5 * weight

        blended_base = (weight * source_marks) + ((1.0 - weight) * cohort_anchor)
        predicted_target_marks = round(
            min(max_m, max(0.0, blended_base + foundation_shift)),
            1,
        )

        impact_delta = round(predicted_target_marks - source_marks, 1)
        projected_sgpi = round(min(10.0, (predicted_target_marks / max_m) * 10.0), 2)
        grade = _compute_grade((predicted_target_marks / max_m) * 100.0)
        status = _compute_status(source_marks, predicted_target_marks, min_m)

        if source_marks < min_m:
            impact_note = f"Weak {source_clean} foundation (<{min_m:g}) creates high risk in {target_clean}."
        elif impact_delta >= 0:
            impact_note = f"Strong {source_clean} score positively boosts {target_clean} by +{impact_delta} marks."
        else:
            impact_note = f"Moderate {source_clean} carryover projects {predicted_target_marks} in {target_clean}."

        dependency_predictions.append({
            "Roll_Number": roll,
            "Student_Name": name,
            "Source_Subject": source_clean,
            "Target_Subject": target_clean,
            "Dependency_Weight": round(weight, 2),
            "Source_Marks": source_marks,
            "Actual_Marks": source_marks,
            "Predicted_Marks": predicted_target_marks,
            "Impact_Delta": impact_delta,
            "Projected_SGPI": projected_sgpi,
            "Max_Marks": max_m,
            "Min_Marks": min_m,
            "Grade": grade,
            "Status": status,
            "Impact_Summary": impact_note,
        })

    return make_json_safe({
        "mode": "prerequisite_dependency",
        "source_subject": source_clean,
        "target_subject": target_clean,
        "dependency_weight": round(weight, 2),
        "rows_processed": len(dependency_predictions),
        "subject_predictions": dependency_predictions,
        "predictions": dependency_predictions,
    })