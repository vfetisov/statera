"""Manual LinkedIn login helper script.

Opens a visible Chromium window so the user can log in to LinkedIn by hand,
then saves the authenticated browser storage state for later reuse.

Never prints credentials, cookies, or tokens.
"""

import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.sources.linkedin.auth import save_linkedin_storage_state  # noqa: E402


def _resolve_storage_state(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    storage_state = _resolve_storage_state(settings.LINKEDIN_STORAGE_STATE)
    try:
        save_linkedin_storage_state(storage_state)
    except Exception as exc:
        print(
            f"LinkedIn login FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
