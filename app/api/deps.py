"""FastAPI dependency that provides a database session per request."""

from collections.abc import Generator
from sqlalchemy.orm import Session
from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session; rollback on error, always close on exit."""
    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
