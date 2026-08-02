"""Manual LinkedIn authentication: save browser storage state for reuse.

This module never requests, reads, or logs credentials, cookies, or tokens.
The user logs in by hand in the opened browser window.
"""

from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"

# URL fragments that indicate the user is not on an authenticated page.
_AUTH_FRAGMENTS = (
    "/login",
    "/uas/login",
    "/checkpoint",
    "/authwall",
    "/challenge",
)

# Cookie domains that indicate a LinkedIn session is present.
_LINKEDIN_COOKIE_DOMAINS = (".linkedin.com", "www.linkedin.com")


def _is_linkedin_url(url: str) -> bool:
    """True if the URL belongs to linkedin.com (or a subdomain)."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _is_auth_url(url: str) -> bool:
    """True if the URL is a login/auth/checkpoint/challenge page."""
    return any(fragment in url for fragment in _AUTH_FRAGMENTS)


def _is_authenticated_url(url: str) -> bool:
    """True if the URL is on linkedin.com and not an auth page."""
    return _is_linkedin_url(url) and not _is_auth_url(url)


def _launch_login_browser(playwright):
    """Launch Chromium for manual login.

    Manual login is ALWAYS headed: it needs a visible GUI window so the user
    can complete LinkedIn's interactive sign-in and pass any challenge. The
    ``PLAYWRIGHT_HEADLESS`` production setting is deliberately ignored here —
    headless jobs never log in automatically and simply fail with
    ``LinkedInAuthenticationRequired`` when the session expires.
    """
    return playwright.chromium.launch(headless=False)


def _select_authenticated_page(context) -> object | None:
    """Return the first open page that looks authenticated, else None."""
    for candidate in context.pages:
        if _is_authenticated_url(candidate.url):
            return candidate
    return None


def _has_linkedin_cookie(context) -> bool:
    """True if the context holds at least one LinkedIn session cookie.

    Only cookie domains are inspected; cookie values are never printed.
    """
    for cookie in context.cookies():
        if cookie.get("domain") in _LINKEDIN_COOKIE_DOMAINS:
            return True
    return False


def _print_page_urls(context) -> None:
    """Print only the open page URLs for debugging (never cookies/tokens)."""
    for index, candidate in enumerate(context.pages):
        print(f"  page {index}: {candidate.url}")


def save_linkedin_storage_state(storage_state_path: Path) -> None:
    """Open a headed Chromium window for manual LinkedIn login and save state.

    The user signs in by hand in the browser. After confirming in the terminal
    (press Enter), the function:

    - inspects every open page in the context and picks an authenticated tab;
    - if none exists, navigates the current page to the LinkedIn feed;
    - verifies the resulting URL is on linkedin.com and not an auth page;
    - verifies the context holds at least one LinkedIn session cookie.

    Only if both checks pass is the storage state saved. On failure, the open
    page URLs are printed and an error is raised without saving anything.
    """
    storage_state_path = Path(storage_state_path)
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = _launch_login_browser(p)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(LINKEDIN_LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")

            print("Please log in to LinkedIn in the opened browser window.")
            print("After signing in, return to this terminal and press Enter.")
            input("Press Enter when you have finished logging in...")

            print("Open pages:")
            _print_page_urls(context)

            # Login may have completed in another tab while the original login
            # page stays open, so prefer an already-authenticated tab.
            page = _select_authenticated_page(context) or page

            if not _is_authenticated_url(page.url):
                page.goto(LINKEDIN_FEED_URL, wait_until="domcontentloaded")
                page.wait_for_load_state("domcontentloaded")

            if not _is_authenticated_url(page.url):
                print("Final page URLs:")
                _print_page_urls(context)
                raise RuntimeError(
                    "Login verification failed: no authenticated LinkedIn "
                    "page found. Storage state was NOT saved."
                )

            if not _has_linkedin_cookie(context):
                print("Final page URLs:")
                _print_page_urls(context)
                raise RuntimeError(
                    "Login verification failed: no LinkedIn session cookie "
                    "found. Storage state was NOT saved."
                )

            context.storage_state(path=str(storage_state_path))
        finally:
            browser.close()

    print(f"LinkedIn storage state saved to: {storage_state_path}")
