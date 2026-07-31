"""Database models.

Importing this module registers all model classes (and their tables) on
``Base.metadata``.
"""

from app.db.models.analysis import Analysis
from app.db.models.company import Company
from app.db.models.job_source import JobSource
from app.db.models.search import Search
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent

__all__ = [
    "Analysis",
    "Company",
    "JobSource",
    "Search",
    "Vacancy",
    "VacancyContent",
]
