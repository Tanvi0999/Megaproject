from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer

# Database and Models
from app import models
from app.database import Base, engine

# Routers
from app.api.v1.auth import router as auth_router
from app.api.v1.endpoints.students import router as students_router
from app.api.v1.endpoints.recommendations import router as recommendations_router
from app.api.v1.endpoints.attendance import router as attendance_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create missing tables; never drop existing tables.
    Base.metadata.create_all(bind=engine)
    yield

# 1. Single App Initialization
app = FastAPI(
    title="AI-Based Intelligent Student Profiling & Career Recommendation System",
    version="0.1.0",
    description="Student profiling, career recommendations, skill-gap analysis, and attendance API with Keycloak.",
    lifespan=lifespan,
)

# 2. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Keycloak Security Infrastructure
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="http://localhost:8080/realms/megaproject/protocol/openid-connect/token"
)

def require_role(required_role: str):
    def role_checker(token: str = Depends(oauth2_scheme)):
        return token
    return role_checker

# 4. Include All Routers Exactly Once
app.include_router(auth_router)
app.include_router(students_router)
app.include_router(recommendations_router)
app.include_router(attendance_router, tags=["Attendance"])

# 5. Root and Health Routes
@app.get("/", tags=["Health"])
def home():
    return {"message": "API is running with Keycloak security and Attendance merged", "docs": "/docs"}

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}