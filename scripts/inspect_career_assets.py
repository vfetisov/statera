"""Print metadata about configured career assets.

Read-only. Never calls an LLM or the database, and never prints asset text,
API keys, or DATABASE_URL. Use this to verify which private files Statera will
use before spending API credits.
"""

import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.career.registry import (  # noqa: E402
    CareerAssetPaths,
    load_career_asset_registry,
)
from app.config import settings  # noqa: E402


def _resolve_asset_path(raw: str | None) -> Path | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    master_brief = _resolve_asset_path(settings.MASTER_CAREER_BRIEF_PATH)
    if master_brief is None:
        print(
            "MASTER_CAREER_BRIEF_PATH is not set. "
            "Add it to .env (see .env.example).",
            file=sys.stderr,
        )
        return 1

    paths = CareerAssetPaths(
        master_career_brief=master_brief,
        master_resume=_resolve_asset_path(settings.MASTER_RESUME_PATH),
        resume_template=_resolve_asset_path(settings.RESUME_TEMPLATE_PATH),
        application_rules=_resolve_asset_path(settings.APPLICATION_RULES_PATH),
        scoring_rules=_resolve_asset_path(settings.SCORING_RULES_PATH),
    )

    try:
        registry = load_career_asset_registry(paths)
    except Exception as exc:
        print(
            f"Could not inspect career assets: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    metadata = registry.metadata()
    for item in sorted(metadata, key=lambda m: m["asset_type"]):
        print(json.dumps(item, ensure_ascii=False))

    print(f"{len(metadata)} career assets loaded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
