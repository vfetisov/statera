"""LinkedIn saved-search smoke test reader.

Reads only the job cards currently visible on a LinkedIn jobs search /
saved-search page. It does not paginate, scroll indefinitely, click Apply or
Easy Apply, open every vacancy, or write to the database.
"""

import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from app.sources.linkedin.browser import (
    LinkedInAuthenticationRequired,
    LinkedInBrowserOptions,
    create_linkedin_browser_context,
    is_linkedin_authentication_url,
    validate_headless_debug_settings,
)

# ---------------------------------------------------------------------------
# LinkedIn-specific selectors and URL constants.
#
# Kept near the top so they can be adjusted if LinkedIn changes its markup.
# Preference is given to robust semantic attributes and to links containing
# "/jobs/view/" instead of deeply nested generated CSS class chains.
# ---------------------------------------------------------------------------

LINKEDIN_BASE_URL = "https://www.linkedin.com"
LINKEDIN_JOB_VIEW_PATH = "/jobs/view/"

# Candidate selector: clickable elements that can represent a whole job card.
_CANDIDATE_SELECTOR = 'button, [role="button"], [tabindex="0"], li'

_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")

# Shallow, defensive selectors used to read the selected-job details pane.
_DETAILS_TITLE_SELECTORS = (
    "h1",
    'h2[class*="job-title"]',
    'h1[class*="job-title"]',
)
_DETAILS_COMPANY_SELECTORS = (
    'a[class*="company-name"]',
    'span[class*="company-name"]',
    'a[href*="/company/"]',
    'span[class*="top-card-layout__second-subline"]',
)
_DETAILS_LOCATION_SELECTORS = (
    'span[class*="location"]',
    'div[class*="location"]',
    'span[class*="bullet"]',
    'span[class*="top-card-layout__tertiary-info"]',
)

# JS: locate the selected-job details pane — an element with a job heading and
# substantial text, outside the page header/navigation.
_FIND_DETAILS_PANE_JS = r"""() => {
  const headings = Array.from(document.querySelectorAll('h1, h2'));
  for (const heading of headings) {
    const text = (heading.innerText || '').trim();
    if (!text || text.length < 4) continue;
    if (heading.closest('header, nav')) continue;
    let node = heading;
    for (let i = 0; i < 8 && node; i++) {
      if (node !== document.body && node !== document.documentElement) {
        if ((node.innerText || '').length > 200) return node;
      }
      node = node.parentElement;
    }
  }
  return null;
}"""

# JS: find the scrollable jobs-list container. Prefers an element that scrolls
# vertically, contains several clickable card candidates and several title-like
# text lines, and is not the document body.
_FIND_JOBS_LIST_CONTAINER_JS = r"""(args) => {
  const sel = args.candidateSelector;
  const all = document.querySelectorAll('*');
  let best = null;
  let bestScroll = 0;
  for (const el of all) {
    if (el === document.body || el === document.documentElement) continue;
    if (!(el.scrollHeight > el.clientHeight + args.minDelta)) continue;
    const clickables = el.querySelectorAll(sel).length;
    if (clickables < args.minClickables) continue;
    const text = el.innerText || '';
    const titleLines = (text.match(/^[A-Za-z][A-Za-z0-9 ,.:()\-]{4,120}$/gm) || []).length;
    if (titleLines < args.minTitles) continue;
    if (el.scrollHeight > bestScroll) {
      bestScroll = el.scrollHeight;
      best = el;
    }
  }
  return best;
}"""

# JS: deduplicate nested card candidates so one visual card yields one
# candidate, preferring the outermost clickable element.
_CANDIDATE_DEDUP_JS = r"""(root, args) => {
  const sel = args.candidateSelector;
  const els = Array.from(root.querySelectorAll(sel));
  return els.map((el) => {
    let node = el.parentElement;
    while (node && node !== root) {
      if (node.matches(sel)) return false;
      node = node.parentElement;
    }
    return true;
  });
}"""

# JS: wait until the page URL exposes a job id different from the previous one.
_URL_JOB_ID_CHANGED_JS = r"""(prev) => {
  const m = window.location.href.match(/(?:currentJobId=|\/jobs\/view\/)(\d+)/);
  return m !== null && m[1] !== prev;
}"""

# Bounded card-extraction settings.
MAX_SCROLL_ROUNDS = 5
SCROLL_STALE_ROUNDS = 2
SCROLL_MIN_WAIT_SECONDS = 0.8
SCROLL_MAX_WAIT_SECONDS = 1.5
JOB_SELECT_TIMEOUT_MS = 4000
CONTAINER_MIN_SCROLL_DELTA = 100
CONTAINER_MIN_CLICKABLES = 3
CONTAINER_MIN_TITLES = 3

# Diagnostic DOM dump settings.
_DUMP_HTML_FILENAME = "linkedin-search-page.html"
_DUMP_PNG_FILENAME = "linkedin-search-page.png"

# Selectors whose counts are printed during a DOM dump.
_DIAGNOSTIC_SELECTORS = (
    "a",
    "a[href]",
    'a[href*="/jobs/view/"]',
    "[data-job-id]",
    "[data-occludable-job-id]",
    "li",
    "ul",
    "main",
)

# Data attributes of interest on the jobs search page.
_DIAGNOSTIC_ATTRIBUTES = ("data-job-id", "data-occludable-job-id", "data-entity-urn")
_MAX_ATTRIBUTE_ELEMENTS = 30
_MAX_SCROLLABLE_CONTAINERS = 20

# JS: collect elements carrying the job-related data attributes.
# Receives {"attributes": [...], "limit": N} via page.evaluate()'s second arg.
_FIND_ATTRIBUTE_MATCHES_JS = r"""(args) => {
  const names = args.attributes;
  const out = [];
  const els = document.querySelectorAll(
    '[data-job-id], [data-occludable-job-id], [data-entity-urn]'
  );
  for (const el of els) {
    if (out.length >= args.limit) break;
    const attrs = {};
    for (const name of names) {
      if (el.hasAttribute(name)) attrs[name] = el.getAttribute(name);
    }
    const text = (el.innerText || el.textContent || "")
      .replace(/\s+/g, " ")
      .trim();
    out.push({
      tag: el.tagName.toLowerCase(),
      attrs: attrs,
      text: text.slice(0, 120),
    });
  }
  return out;
}"""

# JS: collect scrollable containers (scrollHeight > clientHeight + 50).
# Receives {"limit": N} via page.evaluate()'s second arg.
_FIND_SCROLLABLE_CONTAINERS_JS = r"""(args) => {
  const out = [];
  const all = document.querySelectorAll('*');
  for (const el of all) {
    if (out.length >= args.limit) break;
    if (el.scrollHeight > el.clientHeight + 50) {
      let cls = '';
      if (typeof el.className === 'string') cls = el.className;
      const text = (el.innerText || el.textContent || "")
        .replace(/\s+/g, " ")
        .trim();
      out.push({
        tag: el.tagName.toLowerCase(),
        id: el.id || null,
        className: cls || null,
        clientHeight: el.clientHeight,
        scrollHeight: el.scrollHeight,
        anchors: el.querySelectorAll('a').length,
        dataJobId: el.querySelectorAll('[data-job-id]').length,
        text: text.slice(0, 100),
      });
    }
  }
  return out;
}"""


@dataclass
class LinkedInJobPreview:
    """Minimal visible info about one LinkedIn job card."""

    external_id: str | None
    title: str | None
    company: str | None
    location: str | None
    url: str | None


def extract_job_id(url: str) -> str | None:
    """Extract the numeric LinkedIn job ID from a ``/jobs/view/<id>/`` URL."""
    if not url:
        return None
    match = _JOB_ID_RE.search(url)
    return match.group(1) if match else None


def canonical_job_url(external_id: str) -> str:
    """Build a canonical LinkedIn job URL without tracking parameters."""
    return f"{LINKEDIN_BASE_URL}{LINKEDIN_JOB_VIEW_PATH}{external_id}/"


def extract_current_job_id(url: str) -> str | None:
    """Extract the ``currentJobId`` query parameter from a LinkedIn URL."""
    if not url:
        return None
    try:
        params = parse_qs(urlsplit(url).query)
    except ValueError:
        return None
    values = params.get("currentJobId")
    return values[0] if values else None


def _job_id_from_url(url: str) -> str | None:
    """Job id from a URL: ``/jobs/view/<id>/`` or ``currentJobId=<id>``."""
    return extract_job_id(url) or extract_current_job_id(url)


def to_absolute_url(url: str | None) -> str | None:
    """Convert a relative LinkedIn URL to an absolute URL.

    Absolute URLs pass through unchanged, protocol-relative (``//``) URLs get
    ``https:``, and root-relative (``/``) URLs get the LinkedIn origin.
    """
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return LINKEDIN_BASE_URL + url
    return None


def _normalize_job_url(url: str | None) -> str | None:
    """Normalize a job URL for deduplication (strip query, fragment, slash)."""
    if not url:
        return None
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def _job_key(external_id: str | None, url: str | None) -> str | None:
    """Dedup key for a job: external_id when available, otherwise normalized URL."""
    if external_id:
        return f"id:{external_id}"
    normalized = _normalize_job_url(url)
    return f"url:{normalized}" if normalized else None


def deduplicate(previews: list[LinkedInJobPreview]) -> list[LinkedInJobPreview]:
    """Deduplicate previews by ``external_id`` when available, else normalized URL.

    Preserves the order of first appearance.
    """
    seen: set[str] = set()
    unique: list[LinkedInJobPreview] = []
    for preview in previews:
        key = _job_key(preview.external_id, preview.url)
        if key is None:
            unique.append(preview)
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(preview)
    return unique


_TITLE_LINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.:()&\-/'+]{3,119}$")
_PLACE_LINE_RE = re.compile(
    r"^[A-Za-z][A-Za-z .\-']*(?:,\s*[A-Za-z][A-Za-z .\-']*){1,3}$"
)
_PUNCTUATION_ONLY_RE = re.compile(r"^[\W_]+$")
_POSTING_AGE_RE = re.compile(
    r"^(?:active\s+)?\d+\s+"
    r"(day|days|week|weeks|month|months|hour|hours|minute|minutes)\s+ago$",
    re.IGNORECASE,
)
_COMPANY_SUFFIXES = {"inc", "inc.", "ltd", "llc", "corp", "gmbh", "sa", "bv"}
_WORK_MODE_WORDS = ("remote", "hybrid", "on-site")
_WORK_MODE_SUFFIXES = ("(remote)", "(hybrid)", "(on-site)")
_STANDALONE_SEPARATORS = ("·", "•", "|")
_METADATA_PREFIXES = (
    "posted",
    "promoted",
    "actively recruiting",
    "actively reviewing",
    "easy apply",
    "viewed",
    "applied",
    "saved",
    "be an early applicant",
)


def _looks_like_title(line: str) -> bool:
    """True if a single line looks like a job title."""
    if not line:
        return False
    if len(line) < 4 or len(line) > 120:
        return False
    if line.lower().startswith("posted"):
        return False
    return bool(_TITLE_LINE_RE.match(line))


def _normalize_line(line: str) -> str:
    """Collapse repeated whitespace and trim a line."""
    return re.sub(r"\s+", " ", line).strip()


def _strip_verified(line: str) -> str:
    """Remove the '(Verified job)' presentational suffix."""
    return re.sub(r"\s*\(Verified job\)\s*", "", line).strip()


def _is_metadata(line: str) -> bool:
    """True for metadata lines that must not become title/company/location."""
    lower = line.lower()
    return any(
        lower == prefix or lower.startswith(prefix) for prefix in _METADATA_PREFIXES
    )


def _is_separator(line: str) -> bool:
    return line in _STANDALONE_SEPARATORS


def _is_punctuation_only(line: str) -> bool:
    return bool(line) and bool(_PUNCTUATION_ONLY_RE.match(line))


def _looks_like_posting_age(line: str) -> bool:
    return bool(_POSTING_AGE_RE.match(line.strip()))


def _looks_like_location_line(line: str) -> bool:
    """Heuristic: does a line read like a location rather than a company?"""
    lower = line.lower()
    if any(word in lower for word in _WORK_MODE_WORDS):
        return True
    if "·" in line:
        return True
    if not _PLACE_LINE_RE.match(line.strip()):
        return False
    last = lower.split()[-1].rstrip(".") if lower.split() else ""
    return last not in _COMPANY_SUFFIXES


def _apply_preview_safeguards(
    title: str | None,
    company: str | None,
    location: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Drop low-confidence company/location values before returning."""
    if company and company == title:
        company = None
    if location and location == title:
        location = None
    if location and location == company:
        location = None
    if location and _is_punctuation_only(location):
        location = None
    return title, company, location


def parse_job_card_lines(
    lines: list[str],
) -> tuple[str | None, str | None, str | None]:
    """Parse normalized card lines into (title, company, location).

    Normalizes each line (trim, collapse whitespace, drop empty lines and
    standalone separators, drop duplicate adjacent lines), strips "(Verified
    job)" markers, ignores metadata lines, and then picks:

    - title: the first meaningful line;
    - location: the first line that looks like a location;
    - company: the first remaining line that is not the title, location,
      metadata, punctuation-only, work-mode-suffixed, or a posting-age line.

    Confidence safeguards are applied before returning.
    """
    normalized: list[str] = []
    for raw_line in lines:
        line = _normalize_line(raw_line)
        line = _strip_verified(line)
        if not line or _is_separator(line):
            continue
        normalized.append(line)

    # Remove duplicate adjacent lines.
    cleaned: list[str] = []
    for line in normalized:
        if not cleaned or cleaned[-1] != line:
            cleaned.append(line)

    meaningful = [line for line in cleaned if not _is_metadata(line)]
    if not meaningful:
        return (None, None, None)

    title = meaningful[0]
    if len(title) < 2:
        return (None, None, None)

    rest = [line for line in meaningful[1:] if line != title]

    location: str | None = None
    for line in rest:
        if _looks_like_location_line(line):
            location = line
            break

    company: str | None = None
    for line in rest:
        if line == location:
            continue
        if _is_punctuation_only(line):
            continue
        if line.lower().endswith(_WORK_MODE_SUFFIXES):
            continue
        if _looks_like_posting_age(line):
            continue
        if _looks_like_location_line(line):
            continue
        company = line
        break

    return _apply_preview_safeguards(title, company, location)


def parse_card_text(text: str) -> tuple[str | None, str | None, str | None]:
    """Compatibility wrapper: parse a multiline string of card text."""
    return parse_job_card_lines(text.splitlines())


def _first_text(handle, selectors: tuple[str, ...]) -> str | None:
    """Return the collapsed inner text of the first matching child, if any."""
    for selector in selectors:
        element = handle.query_selector(selector)
        if element is None:
            continue
        text = " ".join(element.inner_text().split())
        if text:
            return text
    return None


def _card_lines(candidate) -> list[str]:
    """Per-line normalized visible text of a card candidate."""
    return [
        " ".join(line.split())
        for line in candidate.inner_text().splitlines()
        if line.strip()
    ]


def _card_text(candidate) -> str:
    """Normalized visible text of a card candidate (used for deduplication)."""
    return " ".join(_card_lines(candidate))


def _is_card_candidate(candidate) -> bool:
    """Heuristic filter: the candidate should look like a job card, not a control."""
    lines = _card_lines(candidate)
    if len(" ".join(lines)) < 12:
        return False
    return any(_looks_like_title(line) for line in lines)


def _discover_candidates(container) -> list[object]:
    """Return deduplicated card candidates inside the jobs-list container."""
    handles = container.query_selector_all(_CANDIDATE_SELECTOR)
    mask = container.evaluate(
        _CANDIDATE_DEDUP_JS, {"candidateSelector": _CANDIDATE_SELECTOR}
    )
    return [handle for handle, keep in zip(handles, mask) if keep]


def _click_candidate(candidate) -> None:
    """Click a card candidate, preferring an interactive child when needed."""
    tag = candidate.evaluate("(el) => el.tagName.toLowerCase()") or ""
    role = candidate.get_attribute("role") or ""
    interactive = tag in ("button", "a") or role == "button" or (
        candidate.get_attribute("tabindex") is not None
    )
    target = candidate
    if not interactive:
        child = candidate.query_selector("button, [role='button'], a[href]")
        if child is not None:
            target = child
    target.scroll_into_view_if_needed()
    try:
        target.click()
    except Exception:
        target.click(force=True)


def _wait_for_job_id(page, previous_id: str | None) -> str | None:
    """Wait for the URL's job id to change and return it, else None."""
    try:
        page.wait_for_function(
            _URL_JOB_ID_CHANGED_JS,
            arg=previous_id or "",
            timeout=JOB_SELECT_TIMEOUT_MS,
        )
    except Exception:
        pass
    current = _job_id_from_url(page.url)
    if current is None or current == previous_id:
        return None
    return current


def _details_pane(page):
    """Return the selected-job details pane element handle, or None."""
    return page.evaluate_handle(_FIND_DETAILS_PANE_JS).as_element()


def _details_pane_fields(details) -> tuple[str | None, str | None, str | None]:
    """Best-effort title/company/location scoped to the details pane."""
    return (
        _first_text(details, _DETAILS_TITLE_SELECTORS),
        _first_text(details, _DETAILS_COMPANY_SELECTORS),
        _first_text(details, _DETAILS_LOCATION_SELECTORS),
    )


def _details_pane_text(details) -> str:
    """Normalized text of the details pane, limited to 500 characters."""
    return " ".join(details.inner_text().split())[:500]


def _extract_fields(
    card_lines: list[str], details
) -> tuple[str | None, str | None, str | None]:
    """Combine card parsing with details-pane fallback."""
    title, company, location = parse_job_card_lines(card_lines)
    if details is not None:
        details_title, details_company, details_location = _details_pane_fields(details)
        title = title or details_title
        company = company or details_company
        location = location or details_location
    return _apply_preview_safeguards(title, company, location)


def _debug_card_text(external_id: str, card_lines: list[str], details) -> None:
    """Print raw card/details text for debugging (no cookies/tokens)."""
    print(f"card text for job {external_id}:", file=sys.stderr)
    for line in card_lines:
        print(f"  {line}", file=sys.stderr)
    if details is not None:
        print(
            f"details text for job {external_id}: {_details_pane_text(details)}",
            file=sys.stderr,
        )


def _process_candidate(
    page, candidate, dump_dom: bool = False
) -> LinkedInJobPreview | None:
    """Click a card, wait for the URL job id, and build a preview, else None."""
    previous_id = _job_id_from_url(page.url)
    try:
        _click_candidate(candidate)
    except Exception:
        return None

    external_id = _wait_for_job_id(page, previous_id)
    if external_id is None:
        return None

    # Brief pause for the selected-job details panel to update.
    try:
        page.wait_for_timeout(400)
    except Exception:
        pass

    card_lines = _card_lines(candidate)
    details = _details_pane(page)

    if dump_dom:
        _debug_card_text(external_id, card_lines, details)

    title, company, location = _extract_fields(card_lines, details)
    return LinkedInJobPreview(
        external_id=external_id,
        title=title,
        company=company,
        location=location,
        url=canonical_job_url(external_id),
    )


def _scroll_jobs_list(page, container) -> None:
    """Scroll the jobs-list container (or the window) by one viewport."""
    if container is not None:
        container.evaluate("(el) => { el.scrollTop += el.clientHeight; }")
    else:
        page.evaluate("() => { window.scrollBy(0, window.innerHeight); }")


def _print_attribute_matches(page) -> None:
    """Print info about elements carrying LinkedIn job data attributes."""
    matches = page.evaluate(
        _FIND_ATTRIBUTE_MATCHES_JS,
        {
            "attributes": list(_DIAGNOSTIC_ATTRIBUTES),
            "limit": _MAX_ATTRIBUTE_ELEMENTS,
        },
    )
    print(f"Attribute matches (max {_MAX_ATTRIBUTE_ELEMENTS}):", file=sys.stderr)
    for item in matches:
        attrs = ", ".join(f"{k}={v!r}" for k, v in item["attrs"].items())
        print(f"  <{item['tag']}> {attrs} | text: {item['text']!r}", file=sys.stderr)


def _print_scrollable_containers(page) -> None:
    """Print info about scrollable containers in the page."""
    containers = page.evaluate(
        _FIND_SCROLLABLE_CONTAINERS_JS,
        {"limit": _MAX_SCROLLABLE_CONTAINERS},
    )
    print(
        f"Scrollable containers (max {_MAX_SCROLLABLE_CONTAINERS}):",
        file=sys.stderr,
    )
    for item in containers:
        print(
            f"  <{item['tag']}> id={item['id']!r} class={item['className']!r} "
            f"clientH={item['clientHeight']} scrollH={item['scrollHeight']} "
            f"anchors={item['anchors']} dataJobId={item['dataJobId']} "
            f"| text: {item['text']!r}",
            file=sys.stderr,
        )


def _dump_dom_diagnostics(page, dump_dir: Path) -> None:
    """Save page HTML + a full-page screenshot and print diagnostic DOM info.

    Used to inspect LinkedIn's jobs-search page structure. Never prints
    cookies, tokens, localStorage, sessionStorage, or storage-state contents.

    Failures are reported as a warning on stderr and swallowed, so the smoke
    test can continue with normal extraction.
    """
    dump_dir = Path(dump_dir)
    dump_dir.mkdir(parents=True, exist_ok=True)

    html_path = dump_dir / _DUMP_HTML_FILENAME
    png_path = dump_dir / _DUMP_PNG_FILENAME

    try:
        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)

        print(f"DOM saved to: {html_path.resolve()}", file=sys.stderr)
        print(f"Screenshot saved to: {png_path.resolve()}", file=sys.stderr)

        print("Selector counts:", file=sys.stderr)
        for selector in _DIAGNOSTIC_SELECTORS:
            print(f"  {selector}: {page.locator(selector).count()}", file=sys.stderr)

        _print_attribute_matches(page)
        _print_scrollable_containers(page)
    except Exception as exc:
        print(
            f"DOM diagnostics failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def read_saved_search(
    search_url: str,
    storage_state_path: Path,
    limit: int = 10,
    debug_pause: bool = False,
    dump_dom: bool = False,
    headless: bool = False,
) -> list[LinkedInJobPreview]:
    """Open a LinkedIn saved-search URL and read visible job cards.

    Card-based extraction: finds the scrollable jobs-list container, discovers
    card candidates inside it, and clicks each candidate (up to ``limit``) to
    read the job id from the URL and the preview fields from the card. Bounded
    scrolling (at most ``MAX_SCROLL_ROUNDS`` rounds) reveals more cards.

    ``headless`` controls Chromium execution (local debugging: false, Ubuntu
    production: true). When ``debug_pause`` is true, the browser is kept open
    after extraction and the function waits for Enter in the terminal before
    closing it, so the loaded page can be inspected manually — this is rejected
    in headless mode.

    When ``dump_dom`` is true, the page HTML and a full-page screenshot are
    saved next to the storage state and diagnostic DOM info is printed to help
    inspect LinkedIn's markup.

    Raises ``LinkedInAuthenticationRequired`` when the session has expired,
    and a clear error if the storage state file is missing.
    """
    validate_headless_debug_settings(headless, debug_pause)
    storage_state_path = Path(storage_state_path)

    with sync_playwright() as p:
        browser, context = create_linkedin_browser_context(
            p,
            LinkedInBrowserOptions(
                headless=headless,
                storage_state_path=storage_state_path,
            ),
        )
        page = context.new_page()
        try:
            page.goto(search_url, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")

            if is_linkedin_authentication_url(page.url) or (
                page.locator("#username").count() > 0
            ):
                raise LinkedInAuthenticationRequired()

            # Wait for the first card-like element; the list may be lazy-loaded.
            try:
                page.wait_for_selector(_CANDIDATE_SELECTOR, timeout=10000)
            except Exception:
                pass

            # Optional diagnostic DOM dump (before extraction).
            if dump_dom:
                _dump_dom_diagnostics(page, storage_state_path.parent)

            # One-line page context for debugging (no cookies/tokens).
            print(
                f"page url: {page.url} | page title: {page.title()} | "
                f"open pages: {len(context.pages)}",
                file=sys.stderr,
            )

            container = page.evaluate_handle(
                _FIND_JOBS_LIST_CONTAINER_JS,
                {
                    "candidateSelector": _CANDIDATE_SELECTOR,
                    "minDelta": CONTAINER_MIN_SCROLL_DELTA,
                    "minClickables": CONTAINER_MIN_CLICKABLES,
                    "minTitles": CONTAINER_MIN_TITLES,
                },
            ).as_element()
            if container is None:
                container = page.query_selector("body")
                print(
                    "jobs-list container not found; falling back to page scroll",
                    file=sys.stderr,
                )
            else:
                dims = container.evaluate(
                    "(el) => ({ clientHeight: el.clientHeight, scrollHeight: el.scrollHeight })"
                )
                print(
                    f"jobs-list container: clientHeight={dims['clientHeight']} "
                    f"scrollHeight={dims['scrollHeight']}",
                    file=sys.stderr,
                )

            previews: list[LinkedInJobPreview] = []
            seen_texts: set[str] = set()
            processed_ids: set[str] = set()
            stale_rounds = 0

            for round_index in range(1, MAX_SCROLL_ROUNDS + 1):
                if len(previews) >= limit:
                    break

                candidates = _discover_candidates(container)
                unseen = [
                    candidate
                    for candidate in candidates
                    if _is_card_candidate(candidate)
                    and _card_text(candidate) not in seen_texts
                ]
                for candidate in unseen:
                    seen_texts.add(_card_text(candidate))

                print(
                    f"candidate count (round {round_index}): {len(unseen)}",
                    file=sys.stderr,
                )

                if not unseen:
                    stale_rounds += 1
                    if stale_rounds >= SCROLL_STALE_ROUNDS:
                        break
                else:
                    stale_rounds = 0
                    for candidate in unseen:
                        if len(previews) >= limit:
                            break
                        preview = _process_candidate(
                            page, candidate, dump_dom=dump_dom
                        )
                        if preview is None or preview.external_id in processed_ids:
                            continue
                        processed_ids.add(preview.external_id)
                        previews.append(preview)
                        print(
                            f"extracted job {preview.external_id}: {preview.title!r}",
                            file=sys.stderr,
                        )

                if len(previews) >= limit:
                    break

                _scroll_jobs_list(page, container)
                time.sleep(
                    random.uniform(SCROLL_MIN_WAIT_SECONDS, SCROLL_MAX_WAIT_SECONDS)
                )

            print(f"final unique job count: {len(previews)}", file=sys.stderr)

            if debug_pause:
                print(
                    "Debug pause enabled. Inspect the browser and press Enter to close."
                )
                input()
        finally:
            browser.close()

    return previews
