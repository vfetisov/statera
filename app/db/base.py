"""SQLAlchemy declarative base for all ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models.

    No custom schema is configured, so all future tables will live in the
    default ``public`` schema.
    """
