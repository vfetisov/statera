"""Tests for the headless LinkedIn check script (no browser, no LinkedIn).

The script module is loaded from disk and its ``settings`` / ``read_saved_search``
are replaced with fakes; no Playwright browser is launched.
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from app.sources.linkedin.browser import LinkedInAuthenticationRequired
from app.sources.linkedin.smoke import LinkedInJobPreview

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_settings(**overrides):
    base = {
        "PLAYWRIGHT_HEADLESS": True,
        "LINKEDIN_DEBUG_PAUSE": False,
        "LINKEDIN_DUMP_DOM": False,
        "LINKEDIN_SEARCH_URL": "https://www.linkedin.com/jobs/search/?keywords=python",
        "LINKEDIN_STORAGE_STATE": "var/playwright/linkedin-storage-state.json",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _previews(count: int):
    return [
        LinkedInJobPreview(
            external_id=str(i),
            title=f"Job {i}",
            company="Acme",
            location="Remote",
            url=f"https://www.linkedin.com/jobs/view/{i}/",
        )
        for i in range(count)
    ]


def test_rejects_playwright_headless_false(monkeypatch, capsys) -> None:
    module = _load_script("linkedin_headless_check")
    monkeypatch.setattr(module, "settings", _fake_settings(PLAYWRIGHT_HEADLESS=False))

    assert module.main() == 1
    assert "PLAYWRIGHT_HEADLESS must be true" in capsys.readouterr().err


def test_rejects_debug_pause_in_headless(monkeypatch, capsys) -> None:
    module = _load_script("linkedin_headless_check")
    monkeypatch.setattr(module, "settings", _fake_settings(LINKEDIN_DEBUG_PAUSE=True))

    assert module.main() == 1
    assert "LINKEDIN_DEBUG_PAUSE cannot be enabled in headless mode" in capsys.readouterr().err


def test_result_json_structure(monkeypatch, capsys) -> None:
    module = _load_script("linkedin_headless_check")
    monkeypatch.setattr(module, "settings", _fake_settings())
    monkeypatch.setattr(module, "read_saved_search", lambda **kwargs: _previews(3))

    assert module.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "headless": True,
        "authenticated": True,
        "jobs_found": 3,
    }


def test_zero_jobs_warns_and_succeeds(monkeypatch, capsys) -> None:
    module = _load_script("linkedin_headless_check")
    monkeypatch.setattr(module, "settings", _fake_settings())
    monkeypatch.setattr(module, "read_saved_search", lambda **kwargs: [])

    assert module.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "headless": True,
        "authenticated": True,
        "jobs_found": 0,
    }
    assert "0 jobs found" in captured.err


def test_auth_expired_exits_nonzero(monkeypatch, capsys) -> None:
    module = _load_script("linkedin_headless_check")
    monkeypatch.setattr(module, "settings", _fake_settings())

    def raise_auth(**kwargs):
        raise LinkedInAuthenticationRequired()

    monkeypatch.setattr(module, "read_saved_search", raise_auth)

    assert module.main() == 1
    assert "authentication has expired" in capsys.readouterr().err.lower()
