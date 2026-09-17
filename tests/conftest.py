import os

# Point at the dedicated test database BEFORE importing anything that reads
# settings at import time.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://mise:mise_dev_pw@localhost:5432/mise_test"
)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401 — registers all models on Base.metadata


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session(engine):
    """Each test gets a clean session; tables are truncated after every test
    so tests don't leak state into each other."""
    SessionLocal = sessionmaker(bind=engine, future=True)
    sess = SessionLocal()
    yield sess
    sess.rollback()
    sess.close()
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
