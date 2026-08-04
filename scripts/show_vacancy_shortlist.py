"""Show a human-review shortlist built from existing vacancy-fit analyses.

Read-only. Never calls an LLM, never modifies data, and never prints the full
job description or career assets.

Usage examples:

    python scripts/show_vacancy_shortlist.py
    python scripts/show_vacancy_shortlist.py --min-score 60
    python scripts/show_vacancy_shortlist.py --recommendation strong_match --recommendation consider
    python scripts/show_vacancy_shortlist.py --category REVIEW
    python scripts/show_vacancy_shortlist.py --format json
"""

import argparse
import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.vacancy_analysis import qualified_model_name  # noqa: E402
from app.services.vacancy_shortlist import (  # noqa: E402
    RECOMMENDATION_VALUES,
    SHORTLIST_MAX_LIMIT,
    classify_shortlist_item,
    compact_summary,
    get_vacancy_shortlist,
)

MAX_STRENGTHS = 3
MAX_WEAKNESSES = 3
MAX_RISKS = 3


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show a human-review shortlist from existing analyses."
    )
    parser.add_argument("--limit", type=int, default=50, help="max rows (1-200)")
    parser.add_argument("--min-score", type=int, default=None, dest="min_score")
    parser.add_argument(
        "--recommendation",
        action="append",
        dest="recommendations",
        default=None,
        help="repeatable; one of strong_match/consider/weak_match/reject",
    )
    parser.add_argument(
        "--category",
        choices=["PRIORITY", "REVIEW", "LOW_PRIORITY", "REJECT"],
        default=None,
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args(argv)


def _render_text(item, category: str) -> str:
    summary = compact_summary(item.summary)
    if summary.lower().startswith("professional fit:"):
        professional_fit = summary.split(":", 1)[1].strip()
        professional_lines = [professional_fit] if professional_fit else []
    else:
        professional_lines = [summary]

    lines = [
        f"[{category}] {item.overall_score} overall | "
        f"{item.technical_score} technical | "
        f"{item.leadership_score} leadership | "
        f"{item.location_score} location",
        f"{item.company} — {item.title}" if item.company else item.title,
        item.location or "Location not specified",
        f"Recommendation: {item.recommendation}",
        "",
        "Professional fit:",
        *professional_lines,
        "",
        "Top strengths:",
    ]
    for strength in item.strengths[:MAX_STRENGTHS]:
        lines.append(f"- {strength}")
    lines.append("")
    lines.append("Main gaps:")
    for weakness in item.weaknesses[:MAX_WEAKNESSES]:
        lines.append(f"- {weakness}")
    lines.append("")
    lines.append("Eligibility:")
    risks = item.risks[:MAX_RISKS]
    if risks:
        for risk in risks:
            lines.append(f"- {risk}")
    else:
        lines.append(
            f"Location score {item.location_score}/100; no recorded eligibility risks."
        )
    lines.append("")
    lines.append(f"LinkedIn: {item.source_url}")
    lines.append(f"External ID: {item.external_id}")
    return "\n".join(lines)


def _json_line(item, category: str) -> str:
    return json.dumps(
        {
            "category": category,
            "external_id": item.external_id,
            "title": item.title,
            "company": item.company,
            "location": item.location,
            "source_url": item.source_url,
            "overall_score": item.overall_score,
            "technical_score": item.technical_score,
            "leadership_score": item.leadership_score,
            "location_score": item.location_score,
            "recommendation": item.recommendation,
            "summary": item.summary,
            "strengths": item.strengths,
            "weaknesses": item.weaknesses,
            "risks": item.risks,
            "first_seen_at": item.first_seen_at.isoformat(),
            "analysis_created_at": item.analysis_created_at.isoformat(),
            "model": item.model,
            "prompt_version": item.prompt_version,
        },
        ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not (1 <= args.limit <= SHORTLIST_MAX_LIMIT):
        print(f"--limit must be from 1 through {SHORTLIST_MAX_LIMIT}", file=sys.stderr)
        return 1
    if args.min_score is not None and not (0 <= args.min_score <= 100):
        print("--min-score must be from 0 through 100", file=sys.stderr)
        return 1
    recommendations = None
    if args.recommendations:
        recommendations = set(args.recommendations)
        unknown = recommendations - set(RECOMMENDATION_VALUES)
        if unknown:
            print(f"unknown recommendation values: {sorted(unknown)}", file=sys.stderr)
            return 1

    qualified = qualified_model_name(settings.LLM_PROVIDER, settings.LLM_MODEL)
    prompt_version = settings.VACANCY_ANALYSIS_PROMPT_VERSION

    db = SessionLocal()
    try:
        items = get_vacancy_shortlist(
            db,
            prompt_version=prompt_version,
            qualified_model=qualified,
            minimum_overall_score=args.min_score,
            recommendations=recommendations,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"Could not build shortlist: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        db.close()

    categorized = [(classify_shortlist_item(item), item) for item in items]
    if args.category is not None:
        categorized = [
            (category, item) for category, item in categorized if category == args.category
        ]

    if args.format == "json":
        for category, item in categorized:
            print(_json_line(item, category))
    else:
        for category, item in categorized:
            print(_render_text(item, category))
            print("")

    print(f"{len(categorized)} shortlist items", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
