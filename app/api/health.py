"""Health check endpoints."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> JSONResponse:
    """Readiness probe that verifies the database connection.

    Executes ``SELECT 1`` through SQLAlchemy. If the database is
    unreachable, returns HTTP 503 with a generic body that never exposes
    the password or the full connection string.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unreachable"},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "database": "reachable"},
    )
