import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.services.mark_prediction_service import (
    generate_mark_predictions,
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


@router.post("/predict")
async def predict_marks(
    file: UploadFile = File(...),
    target_subjects: str = Form(...),
):
    """
    Generate subject-wise marks and SGPI predictions
    from an uploaded academic Excel workbook.
    """

    try:
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="Excel filename is required.",
            )

        if not file.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(
                status_code=400,
                detail="Only Excel files (.xlsx, .xls) are supported.",
            )

        workbook_bytes = await file.read()

        if not workbook_bytes:
            raise HTTPException(
                status_code=400,
                detail="Uploaded Excel file is empty.",
            )

        # Parse target_subjects JSON string from multipart/form-data
        try:
            parsed_subjects = json.loads(target_subjects)

            subjects = TypeAdapter(
                list[TargetSubject]
            ).validate_python(parsed_subjects)

        except (json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid target_subjects JSON: {exc}",
            ) from exc

        subjects_dict = [
            subject.model_dump()
            for subject in subjects
        ]

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
            detail="Mark prediction failed.",
        ) from exc