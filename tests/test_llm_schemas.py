"""Tests for the provider-neutral VacancyFitAnalysis schema."""

import pytest
from pydantic import ValidationError

from app.llm.schemas import (
    Recommendation,
    VacancyFitAnalysis,
    validate_score_independence,
)

RECOMMENDATIONS = [
    Recommendation.strong_match,
    Recommendation.consider,
    Recommendation.weak_match,
    Recommendation.reject,
]


def _valid(**overrides):
    data = {
        "overall_score": 80,
        "technical_score": 70,
        "leadership_score": 60,
        "location_score": 90,
        "recommendation": "strong_match",
        "summary": "Strong match with clear evidence in the career brief.",
        "strengths": ["Direct people leadership"],
        "weaknesses": ["No billing analytics evidence"],
        "risks": ["Unspecified work authorization"],
    }
    data.update(overrides)
    return data


def test_valid_response_accepted():
    model = VacancyFitAnalysis.model_validate(_valid())
    assert model.overall_score == 80
    assert model.recommendation == Recommendation.strong_match


def test_recommendation_allows_expected_values():
    for recommendation in RECOMMENDATIONS:
        model = VacancyFitAnalysis.model_validate(
            _valid(recommendation=recommendation.value)
        )
        assert model.recommendation is recommendation


def test_invalid_recommendation_rejected():
    with pytest.raises(ValidationError):
        VacancyFitAnalysis.model_validate(_valid(recommendation="maybe"))


@pytest.mark.parametrize("field", ["overall_score", "technical_score", "leadership_score", "location_score"])
@pytest.mark.parametrize("score", [-1, 101])
def test_score_out_of_range_rejected(field, score):
    with pytest.raises(ValidationError):
        VacancyFitAnalysis.model_validate(_valid(**{field: score}))


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        VacancyFitAnalysis.model_validate(_valid(extra_field="nope"))


def test_empty_list_entries_rejected():
    with pytest.raises(ValidationError):
        VacancyFitAnalysis.model_validate(_valid(strengths=["  "]))


def test_list_item_over_500_chars_rejected():
    with pytest.raises(ValidationError):
        VacancyFitAnalysis.model_validate(_valid(risks=["x" * 501]))


def test_more_than_eight_items_rejected():
    with pytest.raises(ValidationError):
        VacancyFitAnalysis.model_validate(
            _valid(strengths=[f"item {i}" for i in range(9)])
        )


def test_summary_too_short_rejected():
    with pytest.raises(ValidationError):
        VacancyFitAnalysis.model_validate(_valid(summary="s" * 39))


def test_summary_too_long_rejected():
    with pytest.raises(ValidationError):
        VacancyFitAnalysis.model_validate(_valid(summary="s" * 1201))


def test_list_items_are_trimmed():
    model = VacancyFitAnalysis.model_validate(_valid(strengths=["  padded  "]))
    assert model.strengths == ["padded"]


def test_validate_score_independence_preserves_scores():
    model = VacancyFitAnalysis.model_validate(_valid())

    result = validate_score_independence(model)

    assert isinstance(result, VacancyFitAnalysis)
    assert result.overall_score == model.overall_score
    assert result.technical_score == model.technical_score
    assert result.leadership_score == model.leadership_score
    assert result.location_score == model.location_score
    assert result.recommendation == model.recommendation
    assert result.summary == model.summary
    assert result.strengths == model.strengths


def test_validate_score_independence_does_not_rewrite_scores():
    model = VacancyFitAnalysis.model_validate(_valid(overall_score=86, location_score=15))

    result = validate_score_independence(model)

    assert result.overall_score == 86
    assert result.location_score == 15


def test_validate_score_independence_rejects_out_of_range():
    invalid = VacancyFitAnalysis.model_construct(
        overall_score=101,
        technical_score=50,
        leadership_score=50,
        location_score=50,
        recommendation=Recommendation.consider,
        summary="x" * 60,
        strengths=[],
        weaknesses=[],
        risks=[],
    )

    with pytest.raises(ValidationError):
        validate_score_independence(invalid)
