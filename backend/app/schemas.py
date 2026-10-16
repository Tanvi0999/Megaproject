
from pydantic import BaseModel, EmailStr, Field


class StudentProfileCreate(BaseModel):
    student_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    roll_number: str = Field(min_length=1, max_length=30)
    branch: str = Field(min_length=1, max_length=100)
    academic_year: int = Field(ge=1, le=6)
    cgpa: float = Field(ge=0, le=10)
    skills: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)


class StudentProfileResponse(StudentProfileCreate):
    student_id: int
