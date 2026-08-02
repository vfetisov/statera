"""Tests for the shared LinkedIn browser configuration and auth helpers.

No real browser is launched and no LinkedIn access happens. Playwright is only
narrowly stubbed at launch/context entry points.
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.sources.linkedin.browser import (
    LinkedInAuthenticationRequired,
    LinkedInBrowserOptions,
    create_linkedin_browser_context,
    is_linkedin_authentication_url,
    validate_headless_debug_settings,
)


# --- PLAYWRIGHT_HEADLESS setting parsing ------------------------------------


def test_playwright_headless_parsing_from_env_values() -> None:
    assert (
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://x",
            PLAYWRIGHT_HEADLESS="true",
        ).PLAYWRIGHT_HEADLESS
        is True
    )
    assert (
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://x",
            PLAYWRIGHT_HEADLESS="false",
        ).PLAYWRIGHT_HEADLESS
        is False
    )
    assert (
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://x",
        ).PLAYWRIGHT_HEADLESS
        is False
    )


# --- manual login is always headed ------------------------------------------


def test_manual_login_launches_headed() -> None:
    from app.sources.linkedin import auth

    launched: dict = {}

    class FakeChromium:
        def launch(self, **kwargs):
            launched.update(kwargs)
            return object()

    class FakePlaywright:
        chromium = FakeChromium()

    auth._launch_login_browser(FakePlaywright())
    assert launched.get("headless") is False


# --- headless + debug pause validation --------------------------------------


def test_headless_debug_pause_rejected() -> None:
    with pytest.raises(ValueError, match="LINKEDIN_DEBUG_PAUSE cannot be enabled in headless mode"):
        validate_headless_debug_settings(True, True)
    # Allowed combinations do not raise.
    validate_headless_debug_settings(False, True)
    validate_headless_debug_settings(True, False)
    validate_headless_debug_settings(False, False)


# --- authentication URL detection -------------------------------------------


def test_auth_url_detection_for_all_paths() -> None:
    auth_urls = (
        "https://www.linkedin.com/login",
        "https://www.linkedin.com/uas/login?trk=foo",
        "https://www.linkedin.com/checkpoint/ch/verify",
        "https://www.linkedin.com/authwall",
        "https://www.linkedin.com/challenge/abc",
    )
    for url in auth_urls:
        assert is_linkedin_authentication_url(url) is True, url


def test_normal_linkedin_urls_not_auth() -> None:
    normal_urls = (
        "https://www.linkedin.com/feed/",
        "https://www.linkedin.com/jobs/view/123/",
        "https://www.linkedin.com/jobs/search/?keywords=python&currentJobId=9",
        "https://www.linkedin.com/company/acme/",
    )
    for url in normal_urls:
        assert is_linkedin_authentication_url(url) is False, url


# --- missing storage state --------------------------------------------------


def test_missing_storage_state_raises_clear_error() -> None:
    with pytest.raises(FileNotFoundError, match="storage state not found"):
        create_linkedin_browser_context(
            None,
            LinkedInBrowserOptions(
                headless=False,
                storage_state_path=Path("/nonexistent/state.json"),
            ),
        )


# --- browser options + context creation -------------------------------------


def test_browser_options_preserve_headless_and_create_uses_them(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")

    assert LinkedInBrowserOptions(headless=True, storage_state_path=state).headless is True
    assert LinkedInBrowserOptions(headless=False, storage_state_path=state).headless is False

    launched: dict = {}
    context_kwargs: dict = {}

    class FakeBrowser:
        def new_context(self, **kwargs):
            context_kwargs.update(kwargs)
            return "context"

    class FakeChromium:
        def launch(self, **kwargs):
            launched.update(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    browser, context = create_linkedin_browser_context(
        FakePlaywright(),
        LinkedInBrowserOptions(headless=True, storage_state_path=state),
    )

    assert launched["headless"] is True
    assert context_kwargs["storage_state"] == str(state)
    assert context_kwargs["viewport"] == {"width": 1440, "height": 1000}


# --- authentication-required exception --------------------------------------


def test_auth_required_exception_message_safe() -> None:
    message = str(LinkedInAuthenticationRequired())
    assert "LinkedIn authentication has expired" in message
    assert "linkedin_login.py" in message
    # No credentials or storage-state contents in the message.
    assert "password" not in message.lower()
    assert "cookie" not in message.lower()
    assert "token" not in message.lower()


# --- non-login flows use the shared browser options --------------------------


def test_smoke_reader_uses_shared_browser_options(monkeypatch) -> None:
    from app.sources.linkedin import smoke

    captured: dict = {}

    class _Sentinel(Exception):
        pass

    class FakePlaywrightCM:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    def fake_create(playwright, options):
        captured["headless"] = options.headless
        raise _Sentinel()

    monkeypatch.setattr(smoke, "sync_playwright", FakePlaywrightCM)
    monkeypatch.setattr(smoke, "create_linkedin_browser_context", fake_create)

    with pytest.raises(_Sentinel):
        smoke.read_saved_search(
            "https://www.linkedin.com/jobs/search/?keywords=python",
            storage_state_path=Path("/tmp/nonexistent-state.json"),
            headless=True,
        )
    assert captured["headless"] is True


def test_smoke_reader_rejects_headless_debug_pause_without_browser() -> None:
    from app.sources.linkedin import smoke

    with pytest.raises(
        ValueError,
        match="LINKEDIN_DEBUG_PAUSE cannot be enabled in headless mode",
    ):
        smoke.read_saved_search(
            "https://www.linkedin.com/jobs/search/?keywords=python",
            storage_state_path=Path("/tmp/nonexistent-state.json"),
            headless=True,
            debug_pause=True,
        )
