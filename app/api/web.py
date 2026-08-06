"""Web review interface routes (Jinja2 templates, no authentication).

Read-only list/detail pages plus POST-only status mutations. All mutations use
POST and redirect with HTTP 303 to a safe local path. No LLM calls and no
LinkedIn data collection happen from HTTP requests.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.services.vacancy_analysis import qualified_model_name
from app.services.vacancy_review import (
    ALLOWED_TRANSITIONS,
    VALID_CATEGORIES,
    VALID_RECOMMENDATIONS,
    VALID_SORTS,
    VALID_STATUSES,
    InvalidVacancyStatusTransition,
    VacancyNotFoundError,
    count_vacancies_by_status,
    get_review_vacancies,
    get_review_vacancy,
    set_vacancy_review_status,
)
from app.web.presentation import (
    APPLIED_CONFIRM_MESSAGE,
    LEADERSHIP_SCORE_COMPACT_LABEL,
    LEADERSHIP_SCORE_LABEL,
    LOCATION_SCORE_COMPACT_LABEL,
    LOCATION_SCORE_EXPLANATION,
    LOCATION_SCORE_LABEL,
    OVERALL_SCORE_COMPACT_LABEL,
    OVERALL_SCORE_LABEL,
    TECHNICAL_SCORE_COMPACT_LABEL,
    TECHNICAL_SCORE_LABEL,
    action_label,
    category_label,
    recommendation_label,
    sort_label,
    status_label,
)

router = APIRouter()

_BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=_BASE_DIR / "templates")


def _valid_actions(status: str) -> list[tuple[str, str]]:
    """Return (Russian label, target_status) pairs valid for the given status."""
    result: list[tuple[str, str]] = []
    for target in ALLOWED_TRANSITIONS.get(status, ()):
        result.append((action_label(status, target), target))
    return result


def _safe_local_path(path: str) -> str:
    """Return ``path`` if it is a safe local URL, otherwise the list page."""
    if path and path.startswith("/") and not path.startswith("//") and "://" not in path:
        return path
    return "/vacancies"


def _configured():
    qualified = qualified_model_name(settings.LLM_PROVIDER, settings.LLM_MODEL)
    prompt_version = settings.VACANCY_ANALYSIS_PROMPT_VERSION
    return prompt_version, qualified


def _presentation_context() -> dict:
    """Russian display helpers shared by list and detail templates."""
    return {
        "status_label": status_label,
        "recommendation_label": recommendation_label,
        "category_label": category_label,
        "sort_label": sort_label,
        "overall_score_label": OVERALL_SCORE_LABEL,
        "overall_score_compact_label": OVERALL_SCORE_COMPACT_LABEL,
        "technical_score_label": TECHNICAL_SCORE_LABEL,
        "technical_score_compact_label": TECHNICAL_SCORE_COMPACT_LABEL,
        "leadership_score_label": LEADERSHIP_SCORE_LABEL,
        "leadership_score_compact_label": LEADERSHIP_SCORE_COMPACT_LABEL,
        "location_score_label": LOCATION_SCORE_LABEL,
        "location_score_compact_label": LOCATION_SCORE_COMPACT_LABEL,
        "location_score_explanation": LOCATION_SCORE_EXPLANATION,
        "applied_confirm_message": APPLIED_CONFIRM_MESSAGE,
    }


@router.get("/vacancies", response_class=HTMLResponse)
def vacancy_list(
    request: Request,
    status: str = Query("new"),
    category: str | None = Query(None),
    recommendation: str | None = Query(None),
    min_score: int | None = Query(None),
    sort: str = Query("overall"),
    page: int = Query(1),
    page_size: int = Query(20),
    db: Session = Depends(get_db),
):
    if status not in ("new", "selected", "ignored", "applied", "all"):
        raise HTTPException(status_code=400, detail="invalid status")
    if category is not None and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="invalid category")
    if recommendation is not None and recommendation not in VALID_RECOMMENDATIONS:
        raise HTTPException(status_code=400, detail="invalid recommendation")
    if sort not in VALID_SORTS:
        raise HTTPException(status_code=400, detail="invalid sort")
    if min_score is not None and not (0 <= min_score <= 100):
        raise HTTPException(status_code=400, detail="invalid min_score")
    if page < 1 or page_size < 1 or page_size > 200:
        raise HTTPException(status_code=400, detail="invalid pagination")

    prompt_version, qualified = _configured()
    filter_status = None if status == "all" else status
    review_page = get_review_vacancies(
        db,
        prompt_version=prompt_version,
        qualified_model=qualified,
        status=filter_status,
        category=category,
        recommendation=recommendation,
        minimum_score=min_score,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    counts = count_vacancies_by_status(
        db, prompt_version=prompt_version, qualified_model=qualified
    )

    if review_page.total_items == 0:
        if category or recommendation or min_score is not None:
            empty_message = "Нет вакансий, соответствующих текущим фильтрам."
        else:
            empty_message = {
                "new": (
                    "Нет новых проанализированных вакансий. Запустите сбор и "
                    "анализ, или посмотрите «Выбранные»."
                ),
                "selected": "Пока нет выбранных вакансий.",
                "ignored": "Пока нет исключённых вакансий.",
                "applied": "Пока нет отправленных откликов.",
                "all": "Нет вакансий, соответствующих текущим фильтрам.",
            }.get(status, "Нет вакансий, соответствующих текущим фильтрам.")
    else:
        empty_message = ""

    def page_url(p: int) -> str:
        parts = [
            f"status={status}",
            f"sort={sort}",
            f"page_size={page_size}",
            f"page={p}",
        ]
        if category:
            parts.append(f"category={category}")
        if recommendation:
            parts.append(f"recommendation={recommendation}")
        if min_score is not None:
            parts.append(f"min_score={min_score}")
        return "/vacancies?" + "&".join(parts)

    list_return_to = request.url.path
    if request.url.query:
        list_return_to = f"{list_return_to}?{request.url.query}"

    return templates.TemplateResponse(
        request,
        "vacancies/list.html",
        {
            "page": review_page,
            "counts": counts,
            "current_status": status,
            "current_category": category,
            "current_recommendation": recommendation,
            "current_min_score": min_score,
            "current_sort": sort,
            "current_page_size": page_size,
            "categories": VALID_CATEGORIES,
            "recommendations": VALID_RECOMMENDATIONS,
            "sorts": VALID_SORTS,
            "empty_message": empty_message,
            "return_to": list_return_to,
            "valid_actions": _valid_actions,
            "page_url": page_url,
            **_presentation_context(),
        },
    )


@router.get("/vacancies/{external_id}", response_class=HTMLResponse)
def vacancy_detail(request: Request, external_id: str, db: Session = Depends(get_db)):
    prompt_version, qualified = _configured()
    detail = get_review_vacancy(
        db,
        external_id=external_id,
        prompt_version=prompt_version,
        qualified_model=qualified,
    )
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="vacancy not found or has no matching current analysis",
        )
    counts = count_vacancies_by_status(
        db, prompt_version=prompt_version, qualified_model=qualified
    )
    return templates.TemplateResponse(
        request,
        "vacancies/detail.html",
        {
            "detail": detail,
            "counts": counts,
            "valid_actions": _valid_actions,
            **_presentation_context(),
        },
    )


@router.post("/vacancies/{external_id}/status")
def vacancy_set_status(
    external_id: str,
    status: str = Form(...),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    if not external_id.isdigit():
        raise HTTPException(status_code=400, detail="external_id must be numeric")
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="invalid status")

    try:
        set_vacancy_review_status(db, external_id=external_id, status=status)
    except VacancyNotFoundError:
        raise HTTPException(status_code=404, detail="vacancy not found")
    except InvalidVacancyStatusTransition as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"invalid transition {exc.current_status} -> {exc.requested_status}"
            ),
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="could not update vacancy")

    return RedirectResponse(url=_safe_local_path(return_to), status_code=303)
