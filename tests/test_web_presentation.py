"""Tests for the centralized Russian presentation helpers."""

from app.web.presentation import (
    CATEGORY_LABELS,
    LOCATION_SCORE_COMPACT_LABEL,
    LOCATION_SCORE_EXPLANATION,
    LOCATION_SCORE_LABEL,
    RECOMMENDATION_LABELS,
    STATUS_LABELS,
    action_label,
    category_label,
    recommendation_label,
    sort_label,
    status_label,
)


def test_location_score_long_label_is_dostupnost_vacansii():
    assert LOCATION_SCORE_LABEL == "Доступность вакансии"


def test_location_score_compact_label_is_dostupnost():
    assert LOCATION_SCORE_COMPACT_LABEL == "Доступность"


def test_location_score_explanation_is_russian_and_independent():
    text = LOCATION_SCORE_EXPLANATION
    assert "Насколько вакансия практически доступна" in text
    assert "не отражает профессиональное соответствие" in text


def test_status_labels_are_russian():
    assert status_label("new") == "Новые"
    assert status_label("selected") == "Выбранные"
    assert status_label("ignored") == "Исключённые"
    assert status_label("applied") == "Отклики отправлены"


def test_recommendation_labels_are_russian():
    assert recommendation_label("strong_match") == "Отличное соответствие"
    assert recommendation_label("consider") == "Стоит рассмотреть"
    assert recommendation_label("weak_match") == "Слабое соответствие"
    assert recommendation_label("reject") == "Не подходит"


def test_category_labels_are_russian():
    assert category_label("PRIORITY") == "Приоритет"
    assert category_label("REVIEW") == "Требует рассмотрения"
    assert category_label("LOW_PRIORITY") == "Низкий приоритет"
    assert category_label("REJECT") == "Не подходит"


def test_action_labels_are_russian():
    assert action_label("new", "selected") == "Выбрать"
    assert action_label("new", "ignored") == "Исключить"
    assert action_label("selected", "new") == "Вернуть в новые"
    assert action_label("selected", "ignored") == "Исключить"
    assert action_label("selected", "applied") == "Отметить отклик"
    assert action_label("ignored", "new") == "Вернуть в новые"
    assert action_label("ignored", "selected") == "Выбрать"
    assert action_label("applied", "selected") == "Вернуть в выбранные"


def test_internal_stored_values_remain_english():
    # The mapping keys are the canonical stored values and must stay English.
    assert "new" in STATUS_LABELS
    assert "selected" in STATUS_LABELS
    assert "ignored" in STATUS_LABELS
    assert "applied" in STATUS_LABELS
    assert "strong_match" in RECOMMENDATION_LABELS
    assert "consider" in RECOMMENDATION_LABELS
    assert "weak_match" in RECOMMENDATION_LABELS
    assert "reject" in RECOMMENDATION_LABELS
    assert "PRIORITY" in CATEGORY_LABELS
    assert "REVIEW" in CATEGORY_LABELS
    assert "LOW_PRIORITY" in CATEGORY_LABELS
    assert "REJECT" in CATEGORY_LABELS


def test_unknown_values_degrade_safely_to_original():
    assert status_label("mystery") == "mystery"
    assert recommendation_label("mystery") == "mystery"
    assert category_label("mystery") == "mystery"
    assert action_label("mystery", "other") == "other"


def test_sort_labels_are_russian():
    assert sort_label("overall") == "По общему баллу"
    assert sort_label("newest") == "По дате"
    assert sort_label("mystery") == "mystery"
