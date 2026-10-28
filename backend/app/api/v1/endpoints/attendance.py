
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.attendance_service import (
    generate_attendance_predictions,
)

router = APIRouter(
    prefix="/api/v1/attendance",
    tags=["Attendance"],
)


class AttendanceRecord(BaseModel):
    student_name: str = Field(
        ...,
        min_length=1,
        alias="Student_Name",
    )
    roll_number: str = Field(
        ...,
        min_length=1,
        alias="Roll_Number",
    )
    overall_attendance: float = Field(
        ...,
        ge=0,
        le=100,
        alias="Overall_Attendance",
    )


class AttendancePredictionRequest(BaseModel):
    records: list[AttendanceRecord] = Field(..., min_length=1)


@router.post("/predict")
def predict_student_attendance(
    request: AttendancePredictionRequest,
):
    """Predict next-year attendance for one or more students."""
    try:
        records = [
            record.model_dump(by_alias=True)
            for record in request.records
        ]

        predictions = generate_attendance_predictions(records)

        return {
            "count": len(predictions),
            "predictions": predictions,
        }

    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        # Avoid exposing internal details in API error responses.
        raise HTTPException(
            status_code=500,
            detail="Attendance prediction failed.",
        ) from exc
