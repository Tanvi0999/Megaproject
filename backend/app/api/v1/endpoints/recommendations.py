
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_db
from backend.app.models import (
    Student,
    Career,
    Recommendation,
    RecommendedCareer,
    SkillGap,
)
from backend.app.services.recommendation_service import (
    build_recommendations,
)

router = APIRouter(tags=["Career Recommendations"])


class RecommendationGenerateRequest(BaseModel):
    student_id: int = Field(gt=0)
    top_k: int = Field(default=5, ge=1, le=10)


@router.get("/api/students/{student_id}/recommendations")
def get_career_recommendations(
    student_id: int,
    db: Session = Depends(get_db),
):
    student = db.get(Student, student_id)

    if student is None:
        raise HTTPException(
            status_code=404,
            detail="Student not found.",
        )

    return {
        "student_id": student.student_id,
        "student_name": student.student_name,
        "recommendations": build_recommendations(student),
        "note": "Initial rule-based prototype; ML integration is pending.",
    }


@router.get("/api/students/{student_id}/skill-gap")
def get_skill_gap(
    student_id: int,
    db: Session = Depends(get_db),
):
    student = db.get(Student, student_id)

    if student is None:
        raise HTTPException(
            status_code=404,
            detail="Student not found.",
        )

    recommendations = build_recommendations(student)

    return {
        "student_id": student.student_id,
        "skill_gaps": [
            {
                "career": item["career"],
                "missing_skills": item["missing_skills"],
            }
            for item in recommendations
        ],
    }


@router.post("/api/v1/recommendations/generate")
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
            "academic_year": student.academic_year,
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

            saved_results.append(
                {
                    "career_name": item["career"],
                    "rank": rank,
                    "score": score,
                    "matched_skills": item["matched_skills"],
                    "missing_skills": item["missing_skills"],
                }
            )

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
