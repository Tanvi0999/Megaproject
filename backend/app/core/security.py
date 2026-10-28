
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient, PyJWTError

from app.core.config import auth_settings


@lru_cache(maxsize=1)
def get_jwks_client() -> PyJWKClient:
    """Create a cached client for Keycloak's public signing keys."""
    if not auth_settings.jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured yet.",
        )

    return PyJWKClient(auth_settings.jwks_url, timeout=5)


def verify_access_token(token: str) -> dict[str, Any]:
    """Verify a Keycloak JWT and return its validated claims."""
    if not auth_settings.issuer_url or not auth_settings.audience:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured yet.",
        )

    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=auth_settings.issuer_url,
            audience=auth_settings.audience,
            options={"require": ["exp", "iss", "sub"]},
        )

        return payload

    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except HTTPException:
        raise
    except Exception:
        # Avoid exposing internal network or key-fetch details to clients.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication verification is temporarily unavailable.",
        ) from None
