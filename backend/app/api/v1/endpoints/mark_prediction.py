import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.services.mark_prediction_service import (
    generate_mark_predictions,
    generate_pure_sgpi_predictions,
    generate_prerequisite_subject_predictions,
)


router = APIRouter(
    prefix="/api/v1/mark-prediction",
    tags=["Mark Prediction"],
)


class TargetSubject(BaseModel):
    Branch: str = Field(..., min_length=1)
    Semester: int = Field(..., ge=1, le=8)
    Subject_Code: str = Field(..., min_length=1)
    Subject_Name: str = Field(..., min_length=1)
    Max_Marks: float = Field(..., gt=0)
    Min_Marks: float | None = Field(default=None, ge=0)


# ==============================================================================
# FEATURE 1 ENDPOINT: PURE NEXT-SEMESTER SGPI PREDICTION (NO TARGET SUBJECTS)
# ==============================================================================
@router.post("/predict-sgpi")
async def predict_sgpi_only(
        file: UploadFile = File(...),
):
    """
    Feature 1: Predicts Next-Semester SGPI directly from an uploaded CSV or Excel file
    without requiring any target subjects.
    """
    try:
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="Filename is required.",
            )

        if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
            raise HTTPException(
                status_code=400,
                detail="Supported formats: .csv, .xlsx, .xls",
            )

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty.",
            )

        result = generate_pure_sgpi_predictions(
            file_bytes=file_bytes,
            filename=file.filename,
        )

        return {
            "status": "success",
            "filename": file.filename,
            **result,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"SGPI prediction failed: {str(exc)}",
        ) from exc


# ==============================================================================
# FEATURE 2 ENDPOINT: PREREQUISITE-DRIVEN SUBJECT IMPACT PREDICTION
# (e.g., Automata Theory -> Compiler Design using CSV Roll No | Name | Marks)
# ==============================================================================
@router.post("/predict-prerequisite")
async def predict_prerequisite_impact(
        file: UploadFile = File(...),
        source_subject: str = Form(..., description="Prerequisite subject name, e.g. Automata Theory"),
        target_subject: str = Form(..., description="Dependent next-sem subject name, e.g. Compiler Design"),
        dependency_weight: float = Form(0.85, description="Dependency strength from 0.1 to 1.0"),
        max_marks: float = Form(100.0),
        min_marks: float = Form(40.0),
):
    """
    Feature 2: Predicts how marks in a prerequisite subject (e.g., Automata Theory)
    affect the dependent next-semester subject (e.g., Compiler Design) from a CSV/Excel upload.
    """
    try:
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="Filename is required.",
            )

        if not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
            raise HTTPException(
                status_code=400,
                detail="Supported formats: .csv, .xlsx, .xls",
            )

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty.",
            )

        result = generate_prerequisite_subject_predictions(
            file_bytes=file_bytes,
            filename=file.filename,
            source_subject=source_subject,
            target_subject=target_subject,
            dependency_weight=dependency_weight,
            max_marks=max_marks,
            min_marks=min_marks,
        )

        return {
            "status": "success",
            "filename": file.filename,
            **result,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Prerequisite subject prediction failed: {str(exc)}",
        ) from exc


# ==============================================================================
# EXISTING ENDPOINT (PRESERVED FOR BACKWARD COMPATIBILITY)
# ==============================================================================
@router.post("/predict")
async def predict_marks(
        file: UploadFile = File(...),
        target_subjects: str | None = Form(default=None),
):
    """
    Generate subject-wise marks and SGPI predictions
    from an uploaded academic Excel or CSV workbook.
    If target_subjects is omitted, automatically runs Feature 1 (Pure SGPI prediction).
    """
    try:
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="Filename is required.",
            )

        workbook_bytes = await file.read()

        if not workbook_bytes:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty.",
            )

        # If no target_subjects provided or CSV file uploaded, run pure SGPI prediction
        if not target_subjects or not target_subjects.strip() or file.filename.lower().endswith(".csv"):
            result = generate_pure_sgpi_predictions(
                file_bytes=workbook_bytes,
                filename=file.filename,
            )
            return {
                "status": "success",
                "filename": file.filename,
                **result,
            }

        if not file.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(
                status_code=400,
                detail="Only Excel files (.xlsx, .xls) and .csv files are supported.",
            )

        try:
            parsed_subjects = json.loads(target_subjects)

            if isinstance(parsed_subjects, str):
                parsed_subjects = [parsed_subjects]

            if isinstance(parsed_subjects, list) and len(parsed_subjects) > 0 and isinstance(parsed_subjects[0], str):
                subjects_dict = [
                    {
                        "Branch": "Computer Science and Engineering",
                        "Semester": 6,
                        "Subject_Code": "SUB001",
                        "Subject_Name": s,
                        "Max_Marks": 100.0,
                        "Min_Marks": 40.0,
                    }
                    for s in parsed_subjects
                ]
            else:
                subjects = TypeAdapter(
                    list[TargetSubject]
                ).validate_python(parsed_subjects)

                subjects_dict = [
                    subject.model_dump()
                    for subject in subjects
                ]

        except (json.JSONDecodeError, ValidationError) as exc:
            if isinstance(target_subjects, str) and target_subjects.strip():
                raw_list = [s.strip() for s in target_subjects.split(",")]
                subjects_dict = [
                    {
                        "Branch": "Computer Science and Engineering",
                        "Semester": 6,
                        "Subject_Code": "SUB001",
                        "Subject_Name": s,
                        "Max_Marks": 100.0,
                        "Min_Marks": 40.0,
                    }
                    for s in raw_list
                ]
            else:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid target_subjects format: {exc}",
                ) from exc

        result = generate_mark_predictions(
            workbook_bytes=workbook_bytes,
            workbook_name=file.filename,
            target_subjects=subjects_dict,
        )

        return {
            "status": "success",
            "filename": file.filename,
            **result,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Mark prediction failed: {str(exc)}",
        ) from exc