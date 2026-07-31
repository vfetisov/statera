"""Vacancy content version model."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class VacancyContent(Base):
    """One version of a vacancy's job description."""

    __tablename__ = "vacancy_contents"
    __table_args__ = (
        UniqueConstraint("vacancy_id", "version", name="uq_vacancy_contents_vacancy_version"),
        UniqueConstraint("vacancy_id", "content_hash", name="uq_vacancy_contents_vacancy_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_artifact_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    vacancy: Mapped["Vacancy"] = relationship(back_populates="contents")
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="vacancy_content", cascade="all, delete-orphan"
    )
