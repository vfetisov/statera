"""Initialize the Statera database schema.

Reads ``DATABASE_URL`` from the application settings, executes the SQL file
``db/schema/001_initial.sql`` against the database, and commits on success.

The script is safe to run repeatedly (the schema uses IF NOT EXISTS) and never
logs the database password or the full connection string.
"""

import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import settings  # noqa: E402

SCHEMA_FILE = PROJECT_ROOT / "db" / "schema" / "001_initial.sql"


def _redacted_target() -> str:
    """Human-readable database target without credentials."""
    try:
        url = make_url(settings.DATABASE_URL)
        host = url.host or "<host>"
        if url.port:
            host = f"{host}:{url.port}"
        database = url.database or "<db>"
        return f"{host}/{database}"
    except Exception:
        return "<database>"


def main() -> int:
    if not SCHEMA_FILE.is_file():
        print(f"Schema file not found: {SCHEMA_FILE}", file=sys.stderr)
        return 1

    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    if not sql.strip():
        print("Schema file is empty.", file=sys.stderr)
        return 1

    engine = create_engine(settings.DATABASE_URL)
    try:
        raw = engine.raw_connection()
    except Exception as exc:
        print(
            f"Could not connect to database: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        engine.dispose()
        return 1

    try:
        cursor = raw.cursor()
        # Execute the whole file as a single batch. psycopg 3 uses the simple
        # query protocol when no parameters are bound, so the multi-statement
        # SQL file is executed safely without splitting on semicolons.
        cursor.execute(sql)
        raw.commit()
    except Exception as exc:
        raw.rollback()
        print(
            f"Schema initialization FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        raw.close()
        engine.dispose()

    print(f"Schema initialized successfully on {_redacted_target()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
