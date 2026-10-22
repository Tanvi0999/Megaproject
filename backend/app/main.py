
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app import models  # Register SQLAlchemy models
from backend.app.database import Base, engine
from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.endpoints.students import router as students_router
from backend.app.api.v1.endpoints.recommendations import (
    router as recommendations_router,
)
from backend.app.api.v1.endpoints.attendance import (
    router as attendance_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create missing tables; never drop existing tables.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AI-Based Intelligent Student Profiling & Career Recommendation System",
    version="0.1.0",
    description=(
        "Student profiling, career recommendations, "
        "skill-gap analysis, and attendance prediction API."
    ),
    lifespan=lifespan,
)


# Authentication
app.include_router(auth_router)

# Student profiles
app.include_router(students_router)

# Career recommendations and skill-gap analysis
app.include_router(recommendations_router)

# Attendance prediction
app.include_router(attendance_router)


@app.get("/", tags=["Health"])
def home():
    return {
        "message": "Student Career Recommendation API is running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}
