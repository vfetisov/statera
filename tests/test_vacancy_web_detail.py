"""Tests for the review detail page ``GET /vacancies/{external_id}``."""


def test_detail_renders_full_content(web_app):
    client, _, _, seed = web_app
    seed(
        external_id="7",
        jd_text="Full job description text here.",
        strengths=["Strong backend experience", "Scalable systems"],
        weaknesses=["No fintech domain knowledge"],
        risks=["On-site requirement"],
        recommendation="strong_match",
        overall=85,
        location_score=70,
    )

    response = client.get("/vacancies/7")
    assert response.status_code == 200
    assert "Job 7" in response.text
    assert "Full job description text here." in response.text
    assert f"{len('Full job description text here.')} символов" in response.text
    assert "Strong backend experience" in response.text
    assert "No fintech domain knowledge" in response.text
    assert "On-site requirement" in response.text
    # Russian display labels plus preserved canonical values.
    assert "Приоритет" in response.text
    assert 'data-category="PRIORITY"' in response.text
    assert "Отличное соответствие" in response.text
    assert 'data-recommendation="strong_match"' in response.text
    assert "deepseek:deepseek-v4-flash" in response.text
    assert "vacancy-fit-v3" in response.text


def test_detail_links_back_to_list(web_app):
    client, _, _, seed = web_app
    seed(external_id="7")

    response = client.get("/vacancies/7")
    assert response.status_code == 200
    assert 'href="/vacancies"' in response.text
    assert "Открыть в LinkedIn" in response.text
    assert "Вернуться к списку вакансий" in response.text


def test_detail_renders_status_actions(web_app):
    client, _, _, seed = web_app
    seed(external_id="7", status="new")

    response = client.get("/vacancies/7")
    assert response.status_code == 200
    assert 'action="/vacancies/7/status"' in response.text
    assert "Выбрать" in response.text
    assert "Исключить" in response.text


def test_detail_location_score_explanation_rendered(web_app):
    client, _, _, seed = web_app
    seed(external_id="7")

    response = client.get("/vacancies/7")
    assert response.status_code == 200
    assert "score-help" in response.text
    assert "Доступность вакансии" in response.text
    assert "Насколько вакансия практически доступна" in response.text
    assert "не отражает профессиональное соответствие" in response.text


def test_detail_explanation_uses_native_details_without_js(web_app):
    client, _, _, seed = web_app
    seed(external_id="7")

    response = client.get("/vacancies/7")
    assert response.status_code == 200
    assert "<details class=\"score-help\">" in response.text
    assert "<summary" in response.text


def test_detail_get_does_not_call_llm(web_app, monkeypatch):
    client, _, _, seed = web_app
    seed(external_id="7")

    import app.llm.providers.factory as factory

    def _fail(*args, **kwargs):
        raise AssertionError("LLM provider must not be created during GET page rendering")

    monkeypatch.setattr(factory, "create_llm_provider", _fail)
    response = client.get("/vacancies/7")
    assert response.status_code == 200


def test_detail_missing_vacancy_returns_404(web_app):
    client, _, _, seed = web_app
    seed(external_id="7")

    response = client.get("/vacancies/999")
    assert response.status_code == 404


def test_detail_non_numeric_id_returns_404(web_app):
    client, _, _, seed = web_app
    seed(external_id="7")

    response = client.get("/vacancies/abc")
    assert response.status_code == 404
