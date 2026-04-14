"""
SQLAlchemy engine and session factory.
Reuses the existing PostgreSQL instance — all tables use the 'crypto_' prefix.
"""
import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _build_engine():
    settings = get_settings()
    engine = create_engine(
        settings.DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=settings.DEBUG,
    )
    logger.info("DB engine created: %s", settings.DATABASE_URL.split("@")[-1])
    return engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a database session, commit on success, rollback on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables if they don't exist yet."""
    from app.models import db_models  # noqa: F401 — register models
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")


def health_check() -> bool:
    """Return True if the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("DB health check failed: %s", exc)
        return False
