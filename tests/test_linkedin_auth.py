"""Unit tests for LinkedIn authentication helper functions (no browser)."""

from app.sources.linkedin.auth import (
    _has_linkedin_cookie,
    _is_auth_url,
    _is_authenticated_url,
    _is_linkedin_url,
)


# --- _is_linkedin_url ------------------------------------------------------


def test_is_linkedin_url_true() -> None:
    assert _is_linkedin_url("https://www.linkedin.com/feed/") is True
    assert _is_linkedin_url("https://linkedin.com/feed/") is True
    assert _is_linkedin_url("https://jobs.linkedin.com/") is True


def test_is_linkedin_url_false() -> None:
    assert _is_linkedin_url("https://example.com/") is False
    assert _is_linkedin_url("https://notlinkedin.com/") is False
    assert _is_linkedin_url("") is False


# --- _is_auth_url ----------------------------------------------------------


def test_is_auth_url_detects_auth_fragments() -> None:
    assert _is_auth_url("https://www.linkedin.com/login") is True
    assert _is_auth_url("https://www.linkedin.com/uas/login") is True
    assert _is_auth_url("https://www.linkedin.com/checkpoint/ch/xyz") is True
    assert _is_auth_url("https://www.linkedin.com/authwall") is True
    assert _is_auth_url("https://www.linkedin.com/challenge/abc") is True


def test_is_auth_url_false_for_normal_pages() -> None:
    assert _is_auth_url("https://www.linkedin.com/feed/") is False
    assert _is_auth_url("https://www.linkedin.com/jobs/view/123/") is False
    assert _is_auth_url("") is False


# --- _is_authenticated_url -------------------------------------------------


def test_is_authenticated_url_requires_linkedin_and_not_auth() -> None:
    assert _is_authenticated_url("https://www.linkedin.com/feed/") is True
    assert _is_authenticated_url("https://www.linkedin.com/login") is False
    assert _is_authenticated_url("https://www.linkedin.com/authwall") is False
    assert _is_authenticated_url("https://example.com/feed/") is False


# --- _has_linkedin_cookie --------------------------------------------------


class _FakeContext:
    def __init__(self, cookies: list[dict]) -> None:
        self._cookies = cookies

    def cookies(self) -> list[dict]:
        return self._cookies


def test_has_linkedin_cookie_true_for_dot_domain() -> None:
    assert _has_linkedin_cookie(_FakeContext([{"domain": ".linkedin.com"}])) is True


def test_has_linkedin_cookie_true_for_www_domain() -> None:
    assert _has_linkedin_cookie(_FakeContext([{"domain": "www.linkedin.com"}])) is True


def test_has_linkedin_cookie_false_without_linkedin() -> None:
    assert _has_linkedin_cookie(_FakeContext([{"domain": ".google.com"}])) is False


def test_has_linkedin_cookie_false_when_empty() -> None:
    assert _has_linkedin_cookie(_FakeContext([])) is False
