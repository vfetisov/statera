"""Metadata-level tests for the SQLAlchemy models.

These tests validate model metadata only and do not require a live database.
"""

from sqlalchemy import UniqueConstraint

import app.db.models  # noqa: F401  (registers all tables on Base.metadata)
from app.db.base import Base

EXPECTED_TABLES = {
    "job_sources",
    "searches",
    "companies",
    "vacancies",
    "vacancy_contents",
    "analyses",
}


def test_expected_six_tables_exist() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def _unique_constraints(table_name: str) -> list[set[str]]:
    table = Base.metadata.tables[table_name]
    return [
        {column.name for column in constraint.columns}
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]


def test_vacancies_has_expected_unique_constraint() -> None:
    assert {"source_id", "external_id"} in _unique_constraints("vacancies")


def test_vacancy_contents_has_both_unique_constraints() -> None:
    uniques = _unique_constraints("vacancy_contents")
    assert {"vacancy_id", "version"} in uniques
    assert {"vacancy_id", "content_hash"} in uniques


def test_analyses_contains_score_columns() -> None:
    analyses = Base.metadata.tables["analyses"]
    for column in (
        "overall_score",
        "technical_score",
        "leadership_score",
        "location_score",
    ):
        assert column in analyses.columns
