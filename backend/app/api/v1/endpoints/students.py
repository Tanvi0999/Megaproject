
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.models import Student
from app.schemas import (
    StudentProfileCreate,
    StudentProfileResponse,
)

router = APIRouter(
    prefix="/api/students",
    tags=["Students"],
)


@router.post(
    "",
    response_model=StudentProfileResponse,
    status_code=201,
)
def create_student(
    profile: StudentProfileCreate,
    db: Session = Depends(get_db),
):
    student = Student(**profile.model_dump())
    db.add(student)

    try:
        db.commit()
        db.refresh(student)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Email or roll number already exists.",
        ) from exc

    return student


@router.get(
    "",
    response_model=list[StudentProfileResponse],
)
def get_students(db: Session = Depends(get_db)):
    return db.scalars(
        select(Student).order_by(Student.student_id)
    ).all()


@router.get(
    "/{student_id}",
    response_model=StudentProfileResponse,
)
def get_student(
    student_id: int,
    db: Session = Depends(get_db),
):
    student = db.get(Student, student_id)

    if student is None:
        raise HTTPException(
            status_code=404,
            detail="Student not found.",
        )

    return student
