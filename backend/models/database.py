"""
PRODPROOF — Database engine and session management.

Uses SQLAlchemy against MySQL (DATABASE_URL, via the pymysql driver). No
mock DB layer — if the database is unreachable, callers must surface that
explicitly rather than silently falling back to fake data.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,  # avoid "MySQL server has gone away" on long-idle connections
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context-manager form for use outside of FastAPI request handling."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_connection() -> tuple[bool, str | None]:
    """Return (is_healthy, error_message)."""
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True, None
    except Exception as exc:  # noqa: BLE001 - we want to surface any DB error
        return False, str(exc)
