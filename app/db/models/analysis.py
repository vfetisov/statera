"""Vacancy analysis model."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Analysis(Base):
    """One LLM analysis of a specific vacancy-content version."""

    __tablename__ = "analyses"
    __table_args__ = (
        CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)",
            name="ck_analyses_overall_score_range",
        ),
        CheckConstraint(
            "technical_score IS NULL OR (technical_score >= 0 AND technical_score <= 100)",
            name="ck_analyses_technical_score_range",
        ),
        CheckConstraint(
            "leadership_score IS NULL OR (leadership_score >= 0 AND leadership_score <= 100)",
            name="ck_analyses_leadership_score_range",
        ),
        CheckConstraint(
            "location_score IS NULL OR (location_score >= 0 AND location_score <= 100)",
            name="ck_analyses_location_score_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), nullable=False
    )
    vacancy_content_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy_contents.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    overall_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    technical_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    leadership_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    location_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strengths: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    weaknesses: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    risks: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    vacancy: Mapped["Vacancy"] = relationship(back_populates="analyses")
    vacancy_content: Mapped["VacancyContent"] = relationship(
        back_populates="analyses"
    )
