"""Synchronous SQLAlchemy engine, session factory and FastAPI dependency."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# Synchronous engine bound to the configured PostgreSQL database.
# pool_pre_ping verifies connections before use so stale pooled connections
# are transparently discarded.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session.

    The session is always closed when the request finishes, even if an
    exception is raised while it is in use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
