"""Pure tests for LinkedIn description helpers (no browser, no LinkedIn)."""

import pytest

from app.sources.linkedin.description import (
    calculate_content_hash,
    canonical_job_url,
    is_valid_external_id,
    normalize_job_description,
    to_conservative_markdown,
    validate_job_description,
)


# --- normalize_job_description ----------------------------------------------


def test_normalize_newlines() -> None:
    assert normalize_job_description("a\r\nb\rc") == "a\nb\nc"


def test_normalize_trims_trailing_whitespace_per_line() -> None:
    assert normalize_job_description("line1  \nline2 \t\n") == "line1\nline2"


def test_normalize_collapses_excess_blank_lines() -> None:
    assert normalize_job_description("a\n\n\n\n\nb") == "a\n\n\nb"


def test_normalize_preserves_paragraph_separation() -> None:
    text = "First paragraph.\n\nSecond paragraph."
    assert normalize_job_description(text) == text


# --- calculate_content_hash ------------------------------------------------


def test_hash_deterministic_lowercase_hex() -> None:
    h1 = calculate_content_hash("Hello world")
    h2 = calculate_content_hash("Hello world")
    assert h1 == h2
    assert len(h1) == 64
    assert h1 == h1.lower()


def test_hash_same_for_equivalent_normalized_text() -> None:
    assert calculate_content_hash("A  \r\nB\r\n\r\n\r\n") == calculate_content_hash("A\nB")


def test_hash_differs_for_different_text() -> None:
    assert calculate_content_hash("hello") != calculate_content_hash("hello!")


# --- external id + canonical URL -------------------------------------------


def test_is_valid_external_id() -> None:
    assert is_valid_external_id("123") is True
    assert is_valid_external_id("3987654321") is True
    assert is_valid_external_id("") is False
    assert is_valid_external_id("abc") is False
    assert is_valid_external_id("12a") is False


def test_canonical_job_url() -> None:
    assert canonical_job_url("3987654321") == (
        "https://www.linkedin.com/jobs/view/3987654321/"
    )


# --- description validation -------------------------------------------------


def test_short_description_rejected() -> None:
    with pytest.raises(ValueError):
        validate_job_description("1", "short")


def test_empty_description_rejected() -> None:
    with pytest.raises(ValueError):
        validate_job_description("1", "   \n  ")


# --- conservative markdown --------------------------------------------------


def test_markdown_converts_bullets_and_preserves_paragraphs() -> None:
    text = "Intro\n\n• First item\n- Second item\n\nOutro"
    md = to_conservative_markdown(text)
    assert md is not None
    assert "- First item" in md
    assert "- Second item" in md
    assert "Intro" in md
    assert "Outro" in md


def test_markdown_none_for_empty() -> None:
    assert to_conservative_markdown("") is None
