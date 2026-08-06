"""Tests for the review list page ``GET /vacancies`` (SQLite, no LLM)."""


def _seed_defaults(seed):
    seed(external_id="1", recommendation="strong_match", overall=85, location_score=70)
    seed(external_id="2", recommendation="reject", overall=90)
    seed(external_id="3", recommendation="weak_match", overall=55)


def test_list_renders_seeded_vacancies(web_app):
    client, _, _, seed = web_app
    seed(external_id="1")

    response = client.get("/vacancies")
    assert response.status_code == 200
    assert "Statera" in response.text
    assert "Job 1" in response.text
    assert "Новые" in response.text
    assert "Выбранные" in response.text


def test_list_shows_counts(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")
    seed(external_id="2", status="new")
    seed(external_id="3", status="selected")

    response = client.get("/vacancies?status=all")
    assert response.status_code == 200
    assert ">2<" in response.text  # New count
    assert ">1<" in response.text  # Selected count


def test_list_status_tab_filters(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")
    seed(external_id="2", status="selected")

    response = client.get("/vacancies?status=selected")
    assert response.status_code == 200
    assert "Job 2" in response.text
    assert "Job 1" not in response.text


def test_list_category_filter(web_app):
    client, _, _, seed = web_app
    _seed_defaults(seed)

    response = client.get("/vacancies?status=all&category=PRIORITY")
    assert response.status_code == 200
    assert "Job 1" in response.text
    assert "Job 2" not in response.text
    assert "Job 3" not in response.text

    response = client.get("/vacancies?status=all&category=REJECT")
    assert "Job 2" in response.text
    assert "Job 1" not in response.text


def test_list_min_score_filter(web_app):
    client, _, _, seed = web_app
    _seed_defaults(seed)

    response = client.get("/vacancies?status=all&min_score=60")
    assert response.status_code == 200
    assert "Job 1" in response.text
    assert "Job 2" in response.text
    assert "Job 3" not in response.text


def test_list_empty_state_message(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.get("/vacancies?status=selected")
    assert response.status_code == 200
    assert "Пока нет выбранных вакансий." in response.text


def test_list_filtered_empty_state(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.get("/vacancies?status=all&category=REJECT")
    assert response.status_code == 200
    assert "Нет вакансий, соответствующих текущим фильтрам." in response.text


def test_list_pagination(web_app):
    client, _, _, seed = web_app
    for i in range(1, 4):
        seed(external_id=str(i), overall=100 - i)

    response = client.get("/vacancies?status=all&page_size=2&page=2")
    assert response.status_code == 200
    assert "Страница 2 из 2" in response.text
    assert "Job 3" in response.text
    assert "Job 1" not in response.text


def test_list_renders_action_forms(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="new")

    response = client.get("/vacancies?status=new")
    assert response.status_code == 200
    assert 'action="/vacancies/1/status"' in response.text
    assert "Выбрать" in response.text
    assert "Исключить" in response.text


def test_list_invalid_status_returns_400(web_app):
    client, _, _, seed = web_app
    response = client.get("/vacancies?status=bogus")
    assert response.status_code == 400


def test_list_invalid_category_returns_400(web_app):
    client, _, _, seed = web_app
    response = client.get("/vacancies?status=all&category=bogus")
    assert response.status_code == 400


def test_list_invalid_sort_returns_400(web_app):
    client, _, _, seed = web_app
    response = client.get("/vacancies?status=all&sort=bogus")
    assert response.status_code == 400


def test_list_invalid_min_score_returns_400(web_app):
    client, _, _, seed = web_app
    response = client.get("/vacancies?status=all&min_score=150")
    assert response.status_code == 400


def test_list_invalid_pagination_returns_400(web_app):
    client, _, _, seed = web_app
    response = client.get("/vacancies?status=all&page=0")
    assert response.status_code == 400


def test_list_default_page_size(web_app):
    client, _, _, seed = web_app
    for i in range(1, 6):
        seed(external_id=str(i), overall=100 - i)

    response = client.get("/vacancies?status=all")
    assert response.status_code == 200
    assert "Страница 1 из 1" in response.text
    for i in range(1, 6):
        assert f"Job {i}" in response.text


def test_list_location_score_compact_label_is_dostupnost(web_app):
    client, _, _, seed = web_app
    seed(external_id="1")

    response = client.get("/vacancies")
    assert response.status_code == 200
    assert "Доступность" in response.text


def test_list_location_score_explanation_rendered(web_app):
    client, _, _, seed = web_app
    seed(external_id="1")

    response = client.get("/vacancies")
    assert response.status_code == 200
    assert "score-help" in response.text
    assert "Насколько вакансия практически доступна" in response.text
    assert "не отражает профессиональное соответствие" in response.text


def test_list_explanation_uses_native_details_without_js(web_app):
    client, _, _, seed = web_app
    seed(external_id="1")

    response = client.get("/vacancies")
    assert response.status_code == 200
    # A native <details> element: the explanation is reachable without JS.
    assert "<details class=\"score-help\">" in response.text
    assert "<summary" in response.text


def test_list_status_display_labels_are_russian(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="selected")

    response = client.get("/vacancies?status=all")
    assert response.status_code == 200
    assert "Выбранные" in response.text
    assert "Исключённые" in response.text
    assert "Отклики отправлены" in response.text


def test_list_internal_status_values_remain_english(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", status="selected")

    response = client.get("/vacancies?status=all")
    assert response.status_code == 200
    assert 'data-status="selected"' in response.text
    assert 'name="status" value="new"' in response.text


def test_list_category_display_labels_are_russian(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", recommendation="strong_match", overall=85, location_score=70)

    response = client.get("/vacancies?status=all&category=PRIORITY")
    assert response.status_code == 200
    assert "Приоритет" in response.text
    assert 'data-category="PRIORITY"' in response.text


def test_list_recommendation_display_labels_are_russian(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", recommendation="strong_match")

    response = client.get("/vacancies?status=all")
    assert response.status_code == 200
    assert "Отличное соответствие" in response.text
    assert 'data-recommendation="strong_match"' in response.text


def test_list_english_summary_renders_without_error(web_app):
    client, _, _, seed = web_app
    seed(external_id="1", summary="An old English summary from a v3 analysis.")

    response = client.get("/vacancies")
    assert response.status_code == 200
    assert "An old English summary from a v3 analysis." in response.text


def test_list_get_does_not_call_llm(web_app, monkeypatch):
    client, _, _, seed = web_app
    seed(external_id="1")

    import app.llm.providers.factory as factory

    def _fail(*args, **kwargs):
        raise AssertionError("LLM provider must not be created during GET page rendering")

    monkeypatch.setattr(factory, "create_llm_provider", _fail)
    response = client.get("/vacancies")
    assert response.status_code == 200
