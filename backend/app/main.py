from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.v1.auth import router as auth_router

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Career Intel API")

# Define allowed origins
origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.auth import require_role

from app.database import Base, engine, SessionLocal
from app import models
from app.models import (
    Student,
    Career,
    Recommendation,
    RecommendedCareer,
    SkillGap,
)
from pydantic import BaseModel, Field
from app.schemas import (
    StudentProfileCreate,
    StudentProfileResponse,
)

class RecommendationGenerateRequest(BaseModel):
    student_id: int = Field(gt=0)
    top_k: int = Field(default=5, ge=1, le=10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AI-Based Intelligent Student Profiling & Career Recommendation System",
    version="0.1.0",
    description="Student profiling, career recommendations, and skill-gap analysis API.",
    lifespan=lifespan,
)

app.include_router(auth_router)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------------------------------------------------
# PUBLIC ROUTES (No Token Required)
# ---------------------------------------------------------
@app.get("/", tags=["Health"])
def home():
    return {
        "message": "Student Career Recommendation API is running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}

# ---------------------------------------------------------
# FACULTY ROUTES (Requires 'faculty' Keycloak Role)
# ---------------------------------------------------------
@app.post(
    "/api/students",
    response_model=StudentProfileResponse,
    tags=["Students"],
    dependencies=[Depends(require_role("faculty"))]
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
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Email or roll number already exists.",
        )

    return student


@app.get(
    "/api/students",
    response_model=list[StudentProfileResponse],
    tags=["Students"],
    dependencies=[Depends(require_role("faculty"))]
)
def get_students(db: Session = Depends(get_db)):
    return db.scalars(
        select(Student).order_by(Student.student_id)
    ).all()

# ---------------------------------------------------------
# STUDENT ROUTES (Requires 'student' Keycloak Role)
# ---------------------------------------------------------
@app.get(
    "/api/students/{student_id}",
    response_model=StudentProfileResponse,
    tags=["Students"],
    dependencies=[Depends(require_role("student"))]
)
def get_student(
        student_id: int,
        db: Session = Depends(get_db),
):
    student = db.get(Student, student_id)

    if student is None:
        raise HTTPException(status_code=404, detail="Student not found.")

    return student


def build_recommendations(student: Student):
    skills = {
        skill.strip().lower()
        for skill in (student.skills or [])
        if isinstance(skill, str)
    }

    careers = [
        {
            "career": "Data Analyst",
            "required_skills": {
                "python", "sql", "statistics", "data visualization"
            },
        },
        {
            "career": "Machine Learning Engineer",
            "required_skills": {
                "python", "machine learning", "statistics", "sql"
            },
        },
        {
            "career": "Backend Developer",
            "required_skills": {
                "python", "sql", "api development", "git"
            },
        },
    ]

    results = []
    for career in careers:
        required = career["required_skills"]
        matched = sorted(skills & required)
        missing = sorted(required - skills)
        results.append({
            "career": career["career"],
            "match_percentage": round(len(matched) / len(required) * 100, 2),
            "matched_skills": matched,
            "missing_skills": missing,
        })

    return sorted(results, key=lambda item: item["match_percentage"], reverse=True)


@app.get(
    "/api/students/{student_id}/recommendations",
    tags=["Career Recommendations"],
    dependencies=[Depends(require_role("student"))]
)
def get_career_recommendations(
        student_id: int,
        db: Session = Depends(get_db),
):
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found.")

    return {
        "student_id": student.student_id,
        "student_name": student.student_name,
        "recommendations": build_recommendations(student),
        "note": "Initial rule-based prototype; ML integration is pending.",
    }


@app.get(
    "/api/students/{student_id}/skill-gap",
    tags=["Skill Gap Analysis"],
    dependencies=[Depends(require_role("student"))]
)
def get_skill_gap(
        student_id: int,
        db: Session = Depends(get_db),
):
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found.")

    return {
        "student_id": student.student_id,
        "skill_gaps": [
            {
                "career": item["career"],
                "missing_skills": item["missing_skills"],
            }
            for item in build_recommendations(student)
        ],
    }


@app.post(
    "/api/v1/recommendations/generate",
    tags=["Career Recommendations"],
    dependencies=[Depends(require_role("student"))]
)
def generate_recommendations(
        request: RecommendationGenerateRequest,
        db: Session = Depends(get_db),
):
    student = db.get(Student, request.student_id)

    if student is None:
        raise HTTPException(
            status_code=404,
            detail="Student not found.",
        )

    ranked_results = build_recommendations(student)[:request.top_k]

    recommendation = Recommendation(
        student_id=student.student_id,
        model_name="rule-based-prototype",
        model_version="0.1.0",
        input_snapshot={
            "branch": student.branch,
            "academic_year": student.academic_year,  # Fixed: changed from type reference `int` to `student.academic_year`
            "cgpa": student.cgpa,
            "skills": student.skills or [],
            "interests": student.interests or [],
        },
        status="completed",
    )

    try:
        db.add(recommendation)
        db.flush()

        saved_results = []

        for rank, item in enumerate(ranked_results, start=1):
            career = db.scalar(
                select(Career).where(
                    Career.career_name == item["career"]
                )
            )

            score = item["match_percentage"] / 100.0

            recommended_career = RecommendedCareer(
                recommendation_id=recommendation.recommendation_id,
                career_id=career.career_id if career else None,
                career_name=item["career"],
                rank=rank,
                match_score=score,
                matched_skills=item["matched_skills"],
            )

            db.add(recommended_career)
            db.flush()

            for missing_skill in item["missing_skills"]:
                db.add(
                    SkillGap(
                        recommended_career_id=(
                            recommended_career.recommended_career_id
                        ),
                        skill_name=missing_skill,
                        priority="medium",
                        reason=(
                            "Required skill not found in the "
                            "student's current profile."
                        ),
                    )
                )

            saved_results.append({
                "career_name": item["career"],
                "rank": rank,
                "score": score,
                "matched_skills": item["matched_skills"],
                "missing_skills": item["missing_skills"],
            })

        db.commit()

        return {
            "recommendation_id": recommendation.recommendation_id,
            "student_id": student.student_id,
            "model_name": "rule-based-prototype",
            "model_version": "0.1.0",
            "recommendations": saved_results,
        }

    except Exception:
        db.rollback()
        raise