"""Statera FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.web import router as web_router
from app.config import settings

app = FastAPI(title=settings.APP_NAME)

_BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=_BASE_DIR / "static"), name="static")

app.include_router(health_router)
app.include_router(web_router)
