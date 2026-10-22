
from collections.abc import Generator

from sqlalchemy.orm import Session

from backend.app.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Provide a database session for an API request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
