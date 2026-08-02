"""Headless LinkedIn smoke check (no database writes).

Verifies that the existing LinkedIn session and card selectors work without a
GUI. Requires PLAYWRIGHT_HEADLESS=true, reads up to 3 visible cards, and never
writes to PostgreSQL or fetches full descriptions.

Never prints cookies, storage-state contents, or individual descriptions.
"""

import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.sources.linkedin.browser import (  # noqa: E402
    LinkedInAuthenticationRequired,
    validate_headless_debug_settings,
)
from app.sources.linkedin.smoke import read_saved_search  # noqa: E402

CHECK_LIMIT = 3


def _resolve_storage_state(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    if not settings.PLAYWRIGHT_HEADLESS:
        print(
            "PLAYWRIGHT_HEADLESS must be true for the headless check.",
            file=sys.stderr,
        )
        return 1

    try:
        validate_headless_debug_settings(
            settings.PLAYWRIGHT_HEADLESS, settings.LINKEDIN_DEBUG_PAUSE
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    search_url = settings.LINKEDIN_SEARCH_URL
    if not search_url:
        print(
            "LINKEDIN_SEARCH_URL is not set. Add it to .env (see .env.example).",
            file=sys.stderr,
        )
        return 1

    storage_state = _resolve_storage_state(settings.LINKEDIN_STORAGE_STATE)

    try:
        previews = read_saved_search(
            search_url=search_url,
            storage_state_path=storage_state,
            limit=CHECK_LIMIT,
            debug_pause=False,
            dump_dom=settings.LINKEDIN_DUMP_DOM,
            headless=True,
        )
    except LinkedInAuthenticationRequired:
        print(
            "LinkedIn authentication has expired. Recreate the storage-state "
            "file on a GUI machine and deploy it to the server.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            f"LinkedIn headless check FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    count = len(previews)
    print(
        json.dumps(
            {"headless": True, "authenticated": True, "jobs_found": count},
            ensure_ascii=False,
        )
    )

    if count == 0:
        print(
            "Warning: 0 jobs found; LinkedIn selectors or search results may "
            "require inspection.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
