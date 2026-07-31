"""Job source model."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JobSource(Base):
    """A job source (e.g. LinkedIn, HeadHunter, Greenhouse, Lever)."""

    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("code", name="uq_job_sources_code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    searches: Mapped[list["Search"]] = relationship(back_populates="source")
    vacancies: Mapped[list["Vacancy"]] = relationship(back_populates="source")
