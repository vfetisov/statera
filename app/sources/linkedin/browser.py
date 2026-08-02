"""Shared Playwright Chromium launch configuration for non-login flows.

Manual LinkedIn login stays headed and interactive and does NOT use this
module. Every other LinkedIn browser flow (smoke reader, ingestion, description
fetching, headless checks) uses ``create_linkedin_browser_context`` so headed
vs. headless execution is controlled by a single configuration point.
"""

from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Playwright

# Realistic fixed viewport used for all non-login LinkedIn sessions.
DEFAULT_VIEWPORT = {"width": 1440, "height": 1000}

# URL fragments that indicate a LinkedIn authentication state.
_LINKEDIN_AUTH_FRAGMENTS = (
    "/login",
    "/uas/login",
    "/checkpoint",
    "/challenge",
    "/authwall",
)


class LinkedInAuthenticationRequired(RuntimeError):
    """Raised when a non-interactive flow lands on a LinkedIn auth page.

    Non-interactive jobs never attempt to authenticate automatically.
    """

    def __init__(self) -> None:
        super().__init__(
            "LinkedIn authentication has expired. Run scripts/linkedin_login.py "
            "on a machine with a GUI and deploy the refreshed storage-state file."
        )


def is_linkedin_authentication_url(url: str) -> bool:
    """True if the URL indicates a LinkedIn authentication state."""
    return any(fragment in url for fragment in _LINKEDIN_AUTH_FRAGMENTS)


def validate_headless_debug_settings(headless: bool, debug_pause: bool) -> None:
    """Reject interactive debug pause when running headless.

    Interactive pause requires a GUI and would hang a headless job, so it is
    rejected before any browser is launched.
    """
    if headless and debug_pause:
        raise ValueError("LINKEDIN_DEBUG_PAUSE cannot be enabled in headless mode.")


@dataclass(frozen=True)
class LinkedInBrowserOptions:
    """Immutable launch options for a non-login LinkedIn browser session."""

    headless: bool
    storage_state_path: Path


def create_linkedin_browser_context(
    playwright: Playwright,
    options: LinkedInBrowserOptions,
) -> tuple[Browser, BrowserContext]:
    """Launch Chromium and create an authenticated context for LinkedIn.

    Validates that the storage-state file exists, launches Chromium with the
    requested headless setting and a realistic fixed viewport, and returns the
    ``(browser, context)`` pair. Callers must close both safely.

    Storage-state contents are never printed.
    """
    storage_state_path = Path(options.storage_state_path)
    if not storage_state_path.is_file():
        raise FileNotFoundError(
            f"LinkedIn storage state not found: {storage_state_path}. "
            "Run `python scripts/linkedin_login.py` first to authenticate."
        )

    browser = playwright.chromium.launch(headless=options.headless)
    context = browser.new_context(
        storage_state=str(storage_state_path),
        viewport=DEFAULT_VIEWPORT,
    )
    return browser, context
