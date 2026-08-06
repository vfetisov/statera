"""Centralized Russian display labels for the review UI.

Maps canonical internal values (stored unchanged in PostgreSQL) to Russian
user-facing labels. Internal values are never translated back into the
database, and unknown display values degrade safely by returning the original
value so a page never crashes on an unexpected stored value.

Only fixed UI labels are always Russian; stored analysis text (for example an
old English summary) is never rewritten or machine-translated here.
"""

# Canonical stored values -> Russian display labels.
STATUS_LABELS = {
    "new": "Новые",
    "selected": "Выбранные",
    "ignored": "Исключённые",
    "applied": "Отклики отправлены",
}

RECOMMENDATION_LABELS = {
    "strong_match": "Отличное соответствие",
    "consider": "Стоит рассмотреть",
    "weak_match": "Слабое соответствие",
    "reject": "Не подходит",
}

CATEGORY_LABELS = {
    "PRIORITY": "Приоритет",
    "REVIEW": "Требует рассмотрения",
    "LOW_PRIORITY": "Низкий приоритет",
    "REJECT": "Не подходит",
}

# (current_status, target_status) -> Russian action label.
ACTION_LABELS = {
    ("new", "selected"): "Выбрать",
    ("new", "ignored"): "Исключить",
    ("selected", "new"): "Вернуть в новые",
    ("selected", "ignored"): "Исключить",
    ("selected", "applied"): "Отметить отклик",
    ("ignored", "new"): "Вернуть в новые",
    ("ignored", "selected"): "Выбрать",
    ("applied", "selected"): "Вернуть в выбранные",
}

# Score labels. The long label is used where space allows, the compact label
# inside score indicators.
OVERALL_SCORE_LABEL = "Профессиональное соответствие"
OVERALL_SCORE_COMPACT_LABEL = "соответствие"
TECHNICAL_SCORE_LABEL = "Техническое соответствие"
TECHNICAL_SCORE_COMPACT_LABEL = "техническое"
LEADERSHIP_SCORE_LABEL = "Соответствие по управлению"
LEADERSHIP_SCORE_COMPACT_LABEL = "управление"
LOCATION_SCORE_LABEL = "Доступность вакансии"
LOCATION_SCORE_COMPACT_LABEL = "Доступность"

SORT_LABELS = {
    "overall": "По общему баллу",
    "leadership": "По управлению",
    "technical": "По техническому",
    "location": "По доступности",
    "newest": "По дате",
}

# Accessibility explanation shown near the location score on list and detail
# pages. It must remain independent from the professional-fit scores.
LOCATION_SCORE_EXPLANATION = (
    "Насколько вакансия практически доступна с учётом страны найма, формата "
    "работы, права на работу, языка и часового пояса. Эта оценка не отражает "
    "профессиональное соответствие."
)

APPLIED_CONFIRM_MESSAGE = (
    "Отметить отклик? Используйте это только после того, как заявка "
    "действительно отправлена."
)


def status_label(value: str) -> str:
    """Russian display label for a stored status; unknown values pass through."""
    return STATUS_LABELS.get(value, value)


def recommendation_label(value: str) -> str:
    """Russian display label for a stored recommendation; unknown pass through."""
    return RECOMMENDATION_LABELS.get(value, value)


def category_label(value: str) -> str:
    """Russian display label for a stored category; unknown values pass through."""
    return CATEGORY_LABELS.get(value, value)


def action_label(current_status: str, target_status: str) -> str:
    """Russian display label for a status action; unknown pairs pass through."""
    return ACTION_LABELS.get((current_status, target_status), target_status)


def sort_label(value: str) -> str:
    """Russian display label for a sort key; unknown values pass through."""
    return SORT_LABELS.get(value, value)
