"""LinkedIn saved-search smoke test script.

Opens a saved-search / jobs-search URL in a visible Chromium window using the
saved authentication state and prints one JSON object per line for each
currently visible job card.

Never prints storage-state data (cookies/tokens).
"""

import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.sources.linkedin.smoke import read_saved_search  # noqa: E402

DEFAULT_LIMIT = 10


def _resolve_storage_state(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    search_url = settings.LINKEDIN_SEARCH_URL
    if not search_url:
        print(
            "LINKEDIN_SEARCH_URL is not set. "
            "Add it to .env (see .env.example).",
            file=sys.stderr,
        )
        return 1

    storage_state = _resolve_storage_state(settings.LINKEDIN_STORAGE_STATE)

    try:
        previews = read_saved_search(
            search_url=search_url,
            storage_state_path=storage_state,
            limit=DEFAULT_LIMIT,
            debug_pause=settings.LINKEDIN_DEBUG_PAUSE,
            dump_dom=settings.LINKEDIN_DUMP_DOM,
            headless=settings.PLAYWRIGHT_HEADLESS,
        )
    except Exception as exc:
        print(
            f"LinkedIn smoke test FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    for preview in previews:
        print(
            json.dumps(
                {
                    "external_id": preview.external_id,
                    "title": preview.title,
                    "company": preview.company,
                    "location": preview.location,
                    "url": preview.url,
                },
                ensure_ascii=False,
            )
        )

    count = len(previews)
    if count == 0:
        print(
            "Found 0 visible job cards. LinkedIn selectors may need inspection.",
            file=sys.stderr,
        )
    else:
        print(f"Found {count} visible job cards.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
