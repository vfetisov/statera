"""Unit tests for LinkedIn helper functions.

These tests exercise only pure helper logic (URL/ID extraction, deduplication)
and never open a real browser or access LinkedIn.
"""

import inspect

from app.sources.linkedin.smoke import (
    LinkedInJobPreview,
    _DIAGNOSTIC_ATTRIBUTES,
    _DIAGNOSTIC_SELECTORS,
    _DUMP_HTML_FILENAME,
    _DUMP_PNG_FILENAME,
    _FIND_ATTRIBUTE_MATCHES_JS,
    _FIND_SCROLLABLE_CONTAINERS_JS,
    _MAX_ATTRIBUTE_ELEMENTS,
    _MAX_SCROLLABLE_CONTAINERS,
    canonical_job_url,
    deduplicate,
    extract_current_job_id,
    extract_job_id,
    parse_card_text,
    parse_job_card_lines,
    read_saved_search,
    to_absolute_url,
)


# --- extract_job_id --------------------------------------------------------


def test_extract_job_id_from_jobs_view_url() -> None:
    url = "https://www.linkedin.com/jobs/view/3987654321/"
    assert extract_job_id(url) == "3987654321"


def test_extract_job_id_handles_query_and_trailing_path() -> None:
    url = "https://www.linkedin.com/jobs/view/12345/?refId=abc"
    assert extract_job_id(url) == "12345"


def test_extract_job_id_returns_none_when_absent() -> None:
    assert extract_job_id("https://www.linkedin.com/jobs/search/?keywords=x") is None
    assert extract_job_id("") is None
    assert extract_job_id(None) is None


# --- to_absolute_url -------------------------------------------------------


def test_to_absolute_url_passes_absolute_through() -> None:
    url = "https://www.linkedin.com/jobs/view/123/"
    assert to_absolute_url(url) == url


def test_to_absolute_url_handles_root_relative() -> None:
    assert (
        to_absolute_url("/jobs/view/123/")
        == "https://www.linkedin.com/jobs/view/123/"
    )


def test_to_absolute_url_handles_protocol_relative() -> None:
    assert (
        to_absolute_url("//www.linkedin.com/jobs/view/123/")
        == "https://www.linkedin.com/jobs/view/123/"
    )


def test_to_absolute_url_returns_none_for_empty() -> None:
    assert to_absolute_url("") is None
    assert to_absolute_url(None) is None


# --- deduplicate -----------------------------------------------------------


def _preview(external_id: str | None, url: str | None) -> LinkedInJobPreview:
    return LinkedInJobPreview(
        external_id=external_id,
        title="Title",
        company="Company",
        location="Location",
        url=url,
    )


def test_deduplicate_by_external_id() -> None:
    previews = [
        _preview("1", "https://www.linkedin.com/jobs/view/1/"),
        _preview("1", "https://www.linkedin.com/jobs/view/1/?x=2"),
        _preview("2", "https://www.linkedin.com/jobs/view/2/"),
    ]
    result = deduplicate(previews)
    assert len(result) == 2
    assert [p.external_id for p in result] == ["1", "2"]


def test_deduplicate_falls_back_to_url_when_no_external_id() -> None:
    previews = [
        _preview(None, "https://www.linkedin.com/jobs/view/9/"),
        _preview(None, "https://www.linkedin.com/jobs/view/9/"),
        _preview(None, "https://www.linkedin.com/jobs/view/10/"),
    ]
    result = deduplicate(previews)
    assert len(result) == 2
    assert [p.url for p in result] == [
        "https://www.linkedin.com/jobs/view/9/",
        "https://www.linkedin.com/jobs/view/10/",
    ]


def test_deduplicate_keeps_items_without_key() -> None:
    previews = [
        _preview(None, None),
        _preview(None, None),
        _preview("5", "https://www.linkedin.com/jobs/view/5/"),
    ]
    result = deduplicate(previews)
    assert len(result) == 3


def test_deduplicate_by_normalized_url() -> None:
    # Multiple links to the same job that differ only by query string.
    previews = [
        _preview(None, "https://www.linkedin.com/jobs/view/9/"),
        _preview(None, "https://www.linkedin.com/jobs/view/9/?refId=abc"),
    ]
    result = deduplicate(previews)
    assert len(result) == 1


def test_deduplicate_continues_beyond_first_preview() -> None:
    # The first preview duplicates the second; the unique second must be kept.
    previews = [
        _preview("7", "https://www.linkedin.com/jobs/view/7/"),
        _preview("7", "https://www.linkedin.com/jobs/view/7/?refId=x"),
        _preview("8", "https://www.linkedin.com/jobs/view/8/"),
    ]
    result = deduplicate(previews)
    assert [p.external_id for p in result] == ["7", "8"]


def test_deduplicate_preserves_order_of_first_appearance() -> None:
    previews = [
        _preview("3", "https://www.linkedin.com/jobs/view/3/"),
        _preview("1", "https://www.linkedin.com/jobs/view/1/"),
        _preview("3", "https://www.linkedin.com/jobs/view/3/?x=1"),
        _preview("2", "https://www.linkedin.com/jobs/view/2/"),
        _preview("1", "https://www.linkedin.com/jobs/view/1/?y=2"),
    ]
    result = deduplicate(previews)
    assert [p.external_id for p in result] == ["3", "1", "2"]


# --- parse_card_text -------------------------------------------------------


def test_parse_card_text_representative() -> None:
    text = (
        "Senior Backend Engineer\n"
        "Acme Corp\n"
        "Remote · United States\n"
        "Posted 3 days ago"
    )
    assert parse_card_text(text) == (
        "Senior Backend Engineer",
        "Acme Corp",
        "Remote · United States",
    )


def test_parse_card_text_removes_verified_job_marker() -> None:
    text = (
        "Senior Backend Engineer\n"
        "(Verified job)\n"
        "Acme Corp\n"
        "London, England, United Kingdom"
    )
    assert parse_card_text(text) == (
        "Senior Backend Engineer",
        "Acme Corp",
        "London, England, United Kingdom",
    )


def test_parse_card_text_ignores_posted_line() -> None:
    text = (
        "Data Scientist\n"
        "Rivendell Labs\n"
        "New York, NY\n"
        "Posted 2 weeks ago"
    )
    title, company, location = parse_card_text(text)
    assert title == "Data Scientist"
    assert company == "Rivendell Labs"
    assert location == "New York, NY"
    assert "Posted" not in (company or "") and "Posted" not in (location or "")


def test_parse_card_text_returns_none_for_empty() -> None:
    assert parse_card_text("") == (None, None, None)
    assert parse_card_text("   \n  \n") == (None, None, None)


# --- parse_job_card_lines --------------------------------------------------


def test_parse_job_card_lines_title_company_remote_location() -> None:
    lines = ["Technical Account Manager", "Globex Corp", "India (Remote)"]
    assert parse_job_card_lines(lines) == (
        "Technical Account Manager",
        "Globex Corp",
        "India (Remote)",
    )


def test_parse_job_card_lines_removes_verified_job() -> None:
    lines = ["Senior Engineer", "(Verified job)", "Acme", "Remote"]
    title, company, location = parse_job_card_lines(lines)
    assert title == "Senior Engineer"
    assert company == "Acme"
    assert location == "Remote"
    assert "Verified job" not in (company or "")
    assert "Verified job" not in (location or "")


def test_parse_job_card_lines_duplicate_title_line() -> None:
    lines = ["Staff Engineer", "Staff Engineer", "Acme", "Remote"]
    title, company, location = parse_job_card_lines(lines)
    assert title == "Staff Engineer"
    assert company == "Acme"
    assert location == "Remote"


def test_parse_job_card_lines_removes_metadata() -> None:
    lines = [
        "Data Engineer",
        "Acme",
        "Remote",
        "Posted 2 days ago",
        "Easy Apply",
        "Promoted",
    ]
    title, company, location = parse_job_card_lines(lines)
    assert title == "Data Engineer"
    assert company == "Acme"
    assert location == "Remote"
    assert "Posted" not in (company or "")
    assert "Posted" not in (location or "")


def test_parse_job_card_lines_rejects_punctuation_location() -> None:
    lines = ["Senior Technical Account Manager", "Acme", "·"]
    title, company, location = parse_job_card_lines(lines)
    assert company == "Acme"
    assert location is None


def test_parse_job_card_lines_company_not_equal_title() -> None:
    lines = ["Technical Account Manager", "Technical Account Manager", "India (Remote)"]
    title, company, location = parse_job_card_lines(lines)
    assert title == "Technical Account Manager"
    assert company is None
    assert location == "India (Remote)"


def test_parse_job_card_lines_location_not_equal_title_or_company() -> None:
    lines = [
        "Sr. Director, Customer Success Operations",
        "ORBCOMM",
        "Sr. Director, Customer Success Operations",
        "Remote · United States",
    ]
    title, company, location = parse_job_card_lines(lines)
    assert title == "Sr. Director, Customer Success Operations"
    assert company == "ORBCOMM"
    assert location == "Remote · United States"
    assert location != title
    assert location != company


def test_parse_job_card_lines_orbcomm_example() -> None:
    lines = [
        "Sr. Director, Customer Success Operations",
        "ORBCOMM",
        "Remote · United States",
    ]
    title, company, location = parse_job_card_lines(lines)
    assert title == "Sr. Director, Customer Success Operations"
    assert company == "ORBCOMM"
    assert location == "Remote · United States"


def test_parse_job_card_lines_missing_company() -> None:
    lines = ["Staff Engineer", "Remote"]
    title, company, location = parse_job_card_lines(lines)
    assert title == "Staff Engineer"
    assert company is None
    assert location == "Remote"


def test_parse_job_card_lines_missing_location() -> None:
    lines = ["Staff Engineer", "Acme Corp"]
    title, company, location = parse_job_card_lines(lines)
    assert title == "Staff Engineer"
    assert company == "Acme Corp"
    assert location is None


# --- canonical_job_url -----------------------------------------------------


def test_canonical_job_url() -> None:
    assert canonical_job_url("3987654321") == (
        "https://www.linkedin.com/jobs/view/3987654321/"
    )


# --- extract_current_job_id ------------------------------------------------


def test_extract_current_job_id_from_search_url() -> None:
    url = (
        "https://www.linkedin.com/jobs/search/?keywords=python"
        "&currentJobId=3987654321&f_TPR=r2592000"
    )
    assert extract_current_job_id(url) == "3987654321"


def test_extract_current_job_id_returns_none_when_absent() -> None:
    assert extract_current_job_id("https://www.linkedin.com/jobs/search/?q=x") is None
    assert extract_current_job_id("") is None


# --- read_saved_search signature -------------------------------------------


def test_read_saved_search_debug_pause_defaults_to_false() -> None:
    params = inspect.signature(read_saved_search).parameters
    assert params["debug_pause"].default is False


def test_read_saved_search_dump_dom_defaults_to_false() -> None:
    params = inspect.signature(read_saved_search).parameters
    assert params["dump_dom"].default is False


# --- diagnostic DOM dump helpers -------------------------------------------


def _has_newline_inside_quotes(js: str) -> bool:
    """True if a literal newline appears inside a single/double-quoted JS string."""
    quote: str | None = None
    for ch in js:
        if quote is not None:
            if ch == quote:
                quote = None
            elif ch == "\n":
                return True
        elif ch in ("'", '"'):
            quote = ch
    return False


def test_diagnostic_js_has_no_newline_inside_quotes() -> None:
    for js in (_FIND_ATTRIBUTE_MATCHES_JS, _FIND_SCROLLABLE_CONTAINERS_JS):
        assert not _has_newline_inside_quotes(js), "literal newline in JS string"


def test_diagnostic_evaluate_functions_importable() -> None:
    # Both are importable, non-empty function expressions with no leading junk.
    for js in (_FIND_ATTRIBUTE_MATCHES_JS, _FIND_SCROLLABLE_CONTAINERS_JS):
        assert isinstance(js, str) and js
        assert js.startswith("(args) => {")


def test_diagnostic_js_passes_config_as_args() -> None:
    # No Python values are interpolated into the JS source; config comes via args.
    assert "args.limit" in _FIND_ATTRIBUTE_MATCHES_JS
    assert "args.attributes" in _FIND_ATTRIBUTE_MATCHES_JS
    assert "args.limit" in _FIND_SCROLLABLE_CONTAINERS_JS


def test_diagnostic_js_preserves_regex_escape() -> None:
    # Python source must deliver .replace(/\s+/g, " ") unchanged to JavaScript.
    assert r'.replace(/\s+/g, " ")' in _FIND_ATTRIBUTE_MATCHES_JS
    assert r'.replace(/\s+/g, " ")' in _FIND_SCROLLABLE_CONTAINERS_JS


def test_diagnostic_constants_intact() -> None:
    assert _DIAGNOSTIC_SELECTORS == (
        "a",
        "a[href]",
        'a[href*="/jobs/view/"]',
        "[data-job-id]",
        "[data-occludable-job-id]",
        "li",
        "ul",
        "main",
    )
    assert _DIAGNOSTIC_ATTRIBUTES == (
        "data-job-id",
        "data-occludable-job-id",
        "data-entity-urn",
    )
    assert _MAX_ATTRIBUTE_ELEMENTS == 30
    assert _MAX_SCROLLABLE_CONTAINERS == 20
    assert _DUMP_HTML_FILENAME == "linkedin-search-page.html"
    assert _DUMP_PNG_FILENAME == "linkedin-search-page.png"
