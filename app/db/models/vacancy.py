"""Vacancy model."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Vacancy(Base):
    """A job vacancy collected from a source."""

    __tablename__ = "vacancies"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_vacancies_source_external"),
        Index("ix_vacancies_status", "status"),
        Index("ix_vacancies_first_seen_at", "first_seen_at"),
        Index("ix_vacancies_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_sources.id"), nullable=False
    )
    search_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("searches.id"), nullable=True
    )
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("companies.id"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(250), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    remote_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    salary_min: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    salary_max: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="new"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped["JobSource"] = relationship(back_populates="vacancies")
    search: Mapped[Optional["Search"]] = relationship(back_populates="vacancies")
    company: Mapped[Optional["Company"]] = relationship(back_populates="vacancies")
    contents: Mapped[list["VacancyContent"]] = relationship(
        back_populates="vacancy", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="vacancy", cascade="all, delete-orphan"
    )
