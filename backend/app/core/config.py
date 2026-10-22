
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load environment variables from the project root .env file.
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


@dataclass(frozen=True)
class AuthSettings:
    """Configuration for verifying Keycloak access tokens."""

    issuer_url: str = os.getenv("OIDC_ISSUER_URL", "").rstrip("/")
    audience: str = os.getenv("OIDC_AUDIENCE", "")

    @property
    def jwks_url(self) -> str:
        """Keycloak's public signing-key endpoint for this realm."""
        if not self.issuer_url:
            return ""
        return f"{self.issuer_url}/protocol/openid-connect/certs"


auth_settings = AuthSettings()

