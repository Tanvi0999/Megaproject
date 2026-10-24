
from typing import Any

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_token_payload


router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.get("/me")
def get_current_user(
    token_payload: dict[str, Any] = Depends(get_current_token_payload),
) -> dict[str, Any]:
    """Return claims from a verified access token."""
    return {
        "authenticated": True,
        "subject": token_payload["sub"],
        "issuer": token_payload["iss"],
        "claims": token_payload,
    }
