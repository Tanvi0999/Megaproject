import io
import os
import csv
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
import jwt
import httpx
from pydantic import BaseModel

# Database and Models
from app import models
from app.database import Base, engine

# Load prediction model from the services folder
from app.services.attendance_predictor import predict_attendance

# Routers
from app.api.v1.auth import router as auth_router
from app.api.v1.endpoints.students import router as students_router
from app.api.v1.endpoints.recommendations import router as recommendations_router
from app.api.v1.endpoints.attendance import router as attendance_router
from app.api.v1.endpoints.mark_prediction import router as mark_prediction_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title="AI-Based Intelligent Student Profiling & Career Recommendation System",
    version="0.1.0",
    description="Student profiling, career recommendations, skill-gap analysis, and attendance API with Keycloak.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="http://localhost:8080/realms/megaproject/protocol/openid-connect/token"
)

app.include_router(auth_router)
app.include_router(students_router)
app.include_router(recommendations_router)
app.include_router(attendance_router, tags=["Attendance"])
app.include_router(mark_prediction_router)

@app.get("/", tags=["Health"])
def home():
    return {"message": "API is running with Keycloak security and Attendance merged", "docs": "/docs"}

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}

token_auth_scheme = HTTPBearer()

@app.get("/api/v1/secure-dashboard")
async def get_secure_data(credentials: HTTPAuthorizationCredentials = Depends(token_auth_scheme)):
    raw_token = credentials.credentials
    try:
        payload = jwt.decode(raw_token, options={"verify_signature": False})
        email = payload.get("email", "No email provided")
        roles = payload.get("realm_access", {}).get("roles", [])
        return {
            "status": "success",
            "message": f"Welcome, {email}!",
            "is_teacher": "teacher" in roles,
            "token_data": payload
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.DecodeError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

@app.post("/api/v1/predict-attendance")
async def predict_attendance_endpoint(
        file: UploadFile = File(...),
        credentials: HTTPAuthorizationCredentials = Depends(token_auth_scheme)
):
    try:
        contents = await file.read()

        if file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            try:
                text_data = contents.decode('utf-8-sig')
            except UnicodeDecodeError:
                text_data = contents.decode('latin-1')

            sniffer = csv.Sniffer()
            sample = text_data[:2048]
            delimiter = ','
            try:
                dialect = sniffer.sniff(sample)
                delimiter = dialect.delimiter
            except Exception:
                for d in [',', ';', '\t']:
                    if d in sample:
                        delimiter = d
                        break

            reader = csv.reader(io.StringIO(text_data), delimiter=delimiter)
            rows = [row for row in reader if row and any(row)]

            if len(rows) <= 1:
                raise HTTPException(status_code=400, detail="The uploaded CSV file is empty or missing data.")

            df = pd.DataFrame(rows[1:], columns=rows[0][:len(rows[1])])

        if len(df.columns) < 3:
            raise HTTPException(status_code=400, detail="File must contain at least 3 columns.")

        df = df.iloc[:, :3]
        df.columns = ["Student_Name", "Roll_Number", "Overall_Attendance"]

        df["Student_Name"] = df["Student_Name"].astype(str).str.strip()
        df["Roll_Number"] = df["Roll_Number"].astype(str).str.strip()

        df["Overall_Attendance"] = (
            df["Overall_Attendance"]
            .astype(str)
            .str.replace('%', '', regex=False)
            .str.replace(',', '.', regex=False)
            .str.strip()
        )
        df["Overall_Attendance"] = pd.to_numeric(df["Overall_Attendance"], errors='coerce').fillna(0.0)

        df = df.dropna(subset=["Student_Name", "Roll_Number"])

        if df.empty:
            raise HTTPException(status_code=400, detail="No valid data rows found in file.")

        results_df = predict_attendance(df)
        results_list = results_df.to_dict(orient="records")

        return {
            "status": "success",
            "filename": file.filename,
            "rows_processed": len(results_df),
            "predictions": results_list
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

import io
import os
import csv
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
import jwt
import httpx
from pydantic import BaseModel

# Database and Models
from app import models
from app.database import Base, engine

# Load prediction model from the services folder
from app.services.attendance_predictor import predict_attendance

# Routers
from app.api.v1.auth import router as auth_router
from app.api.v1.endpoints.students import router as students_router
from app.api.v1.endpoints.recommendations import router as recommendations_router
from app.api.v1.endpoints.attendance import router as attendance_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title="AI-Based Intelligent Student Profiling & Career Recommendation System",
    version="0.1.0",
    description="Student profiling, career recommendations, skill-gap analysis, and attendance API with Keycloak.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="http://localhost:8080/realms/megaproject/protocol/openid-connect/token"
)

app.include_router(auth_router)
app.include_router(students_router)
app.include_router(recommendations_router)
app.include_router(attendance_router, tags=["Attendance"])
app.include_router(mark_prediction_router)

@app.get("/", tags=["Health"])
def home():
    return {"message": "API is running with Keycloak security and Attendance merged", "docs": "/docs"}

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}

token_auth_scheme = HTTPBearer()

@app.get("/api/v1/secure-dashboard")
async def get_secure_data(credentials: HTTPAuthorizationCredentials = Depends(token_auth_scheme)):
    raw_token = credentials.credentials
    try:
        payload = jwt.decode(raw_token, options={"verify_signature": False})
        email = payload.get("email", "No email provided")
        roles = payload.get("realm_access", {}).get("roles", [])
        return {
            "status": "success",
            "message": f"Welcome, {email}!",
            "is_teacher": "teacher" in roles,
            "token_data": payload
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.DecodeError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

@app.post("/api/v1/predict-attendance")
async def predict_attendance_endpoint(
        file: UploadFile = File(...),
        credentials: HTTPAuthorizationCredentials = Depends(token_auth_scheme)
):
    try:
        contents = await file.read()

        if file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            try:
                text_data = contents.decode('utf-8-sig')
            except UnicodeDecodeError:
                text_data = contents.decode('latin-1')

            sniffer = csv.Sniffer()
            sample = text_data[:2048]
            delimiter = ','
            try:
                dialect = sniffer.sniff(sample)
                delimiter = dialect.delimiter
            except Exception:
                for d in [',', ';', '\t']:
                    if d in sample:
                        delimiter = d
                        break

            reader = csv.reader(io.StringIO(text_data), delimiter=delimiter)
            rows = [row for row in reader if row and any(row)]

            if len(rows) <= 1:
                raise HTTPException(status_code=400, detail="The uploaded CSV file is empty or missing data.")

            df = pd.DataFrame(rows[1:], columns=rows[0][:len(rows[1])])

        if len(df.columns) < 3:
            raise HTTPException(status_code=400, detail="File must contain at least 3 columns.")

        df = df.iloc[:, :3]
        df.columns = ["Student_Name", "Roll_Number", "Overall_Attendance"]

        df["Student_Name"] = df["Student_Name"].astype(str).str.strip()
        df["Roll_Number"] = df["Roll_Number"].astype(str).str.strip()

        df["Overall_Attendance"] = (
            df["Overall_Attendance"]
            .astype(str)
            .str.replace('%', '', regex=False)
            .str.replace(',', '.', regex=False)
            .str.strip()
        )
        df["Overall_Attendance"] = pd.to_numeric(df["Overall_Attendance"], errors='coerce').fillna(0.0)

        df = df.dropna(subset=["Student_Name", "Roll_Number"])

        if df.empty:
            raise HTTPException(status_code=400, detail="No valid data rows found in file.")

        results_df = predict_attendance(df)
        results_list = results_df.to_dict(orient="records")

        return {
            "status": "success",
            "filename": file.filename,
            "rows_processed": len(results_df),
            "predictions": results_list
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Updated Schema to enforce First and Last Name
class RegisterRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str
    role: str
    institutionId: str
    college: str

@app.post("/api/v1/register")
async def register_user(data: RegisterRequest):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            token_res = await client.post(
                "http://localhost:8080/realms/master/protocol/openid-connect/token",
                data={
                    "client_id": "admin-cli",
                    "username": "admin",
                    "password": "admin",
                    "grant_type": "password"
                }
            )
            if token_res.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to authenticate with Keycloak admin.")

            admin_token = token_res.json()["access_token"]
            headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

            # Direct mapping from schema to Keycloak payload
            user_payload = {
                "username": data.email,
                "email": data.email,
                "firstName": data.first_name,
                "lastName": data.last_name,
                "enabled": True,
                "emailVerified": True,
                "credentials": [{"type": "password", "value": data.password, "temporary": False}],
                "attributes": {
                    "institutionId": [data.institutionId],
                    "college": [data.college]
                }
            }

            create_res = await client.post(
                "http://localhost:8080/admin/realms/career-system/users",
                headers=headers,
                json=user_payload
            )

            if create_res.status_code == 409:
                raise HTTPException(status_code=400, detail="An account with this email already exists.")
            if not create_res.is_success:
                raise HTTPException(status_code=400, detail=f"Keycloak error: {create_res.text}")

            user_search_res = await client.get(
                f"http://localhost:8080/admin/realms/career-system/users?username={data.email}",
                headers=headers
            )
            if user_search_res.status_code == 200 and user_search_res.json():
                user_id = user_search_res.json()[0]["id"]
                role_res = await client.get(
                    f"http://localhost:8080/admin/realms/career-system/roles/{data.role}",
                    headers=headers
                )
                if role_res.status_code == 200:
                    role_obj = role_res.json()
                    await client.post(
                        f"http://localhost:8080/admin/realms/career-system/users/{user_id}/role-mappings/realm",
                        headers=headers,
                        json=[role_obj]
                    )

            return {"status": "success", "message": "User registered and assigned role successfully"}
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Keycloak is offline or unreachable.")