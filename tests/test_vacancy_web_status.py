"""Tests for status mutation ``POST /vacancies/{external_id}/status``."""

from sqlalchemy import select

from app.db.models.vacancy import Vacancy


def _status_of(session_factory, external_id):
    db = session_factory()
    try:
        vacancy = db.scalar(select(Vacancy).where(Vacancy.external_id == external_id))
        return vacancy.status if vacancy is not None else None
    finally:
        db.close()


def test_post_valid_transition_redirects_and_updates(web_app):
    client, session_factory, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.post(
        "/vacancies/1/status",
        data={"status": "selected", "return_to": "/vacancies?status=selected"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/vacancies?status=selected"
    assert _status_of(session_factory, "1") == "selected"


def test_post_valid_transition_ignored(web_app):
    client, session_factory, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.post(
        "/vacancies/1/status",
        data={"status": "ignored", "return_to": "/vacancies"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert _status_of(session_factory, "1") == "ignored"


def test_post_applied_requires_confirmed_client(web_app):
    # The confirm dialog is a client-side concern; the POST must still succeed.
    client, session_factory, _, seed = web_app
    seed(external_id="1", status="selected")

    response = client.post(
        "/vacancies/1/status",
        data={"status": "applied", "return_to": "/vacancies"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert _status_of(session_factory, "1") == "applied"


def test_post_invalid_transition_returns_409(web_app):
    client, session_factory, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.post(
        "/vacancies/1/status",
        data={"status": "applied", "return_to": "/vacancies"},
    )
    assert response.status_code == 409
    assert "invalid transition new -> applied" in response.text
    assert _status_of(session_factory, "1") == "new"


def test_post_invalid_status_returns_422(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.post(
        "/vacancies/1/status",
        data={"status": "bogus", "return_to": "/vacancies"},
    )
    assert response.status_code == 422


def test_post_missing_vacancy_returns_404(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.post(
        "/vacancies/999/status",
        data={"status": "selected", "return_to": "/vacancies"},
    )
    assert response.status_code == 404


def test_post_non_numeric_id_returns_400(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.post(
        "/vacancies/abc/status",
        data={"status": "selected", "return_to": "/vacancies"},
    )
    assert response.status_code == 400


def test_post_default_return_to_list(web_app):
    client, session_factory, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.post(
        "/vacancies/1/status",
        data={"status": "selected"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/vacancies"
    assert _status_of(session_factory, "1") == "selected"


def test_post_unsafe_return_to_falls_back_to_list(web_app):
    client, session_factory, _, seed = web_app
    seed(external_id="1", status="new")

    for unsafe in ("https://evil.example", "//evil.example", "javascript:alert(1)"):
        response = client.post(
            "/vacancies/1/status",
            data={"status": "ignored", "return_to": unsafe},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/vacancies"

    assert _status_of(session_factory, "1") == "ignored"


def test_post_updates_status_counts(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")
    seed(external_id="2", status="new")

    client.post("/vacancies/1/status", data={"status": "selected"})

    response = client.get("/vacancies?status=new")
    assert response.status_code == 200
    assert "Job 2" in response.text
    assert "Job 1" not in response.text
