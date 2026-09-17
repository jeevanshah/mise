from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for every model in the app."""


engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Session:
    """FastAPI dependency — yields a session, closes it after the request.
    Commit/rollback is the caller's responsibility (see app/services/audit_service.py
    for the pattern every mutating endpoint should use from Epic 1 step 4 onward)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
