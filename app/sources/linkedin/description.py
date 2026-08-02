"""LinkedIn full job-description reader.

Fetches the current job description for a single LinkedIn vacancy and returns
it as normalized plain text plus conservative Markdown. All LinkedIn-specific
selectors live here. Never exposes credentials, cookies, tokens, or
storage-state contents.
"""

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

LINKEDIN_JOB_VIEW_URL = "https://www.linkedin.com/jobs/view/{external_id}/"

# URL fragments that indicate the user is not on an authenticated page.
_AUTH_FRAGMENTS = ("/login", "/uas/login", "/checkpoint", "/authwall", "/challenge")

# Minimum accepted length for a real job description.
_MIN_DESCRIPTION_CHARS = 200

# Navigation / page-chrome markers used to reject whole-page extraction.
_NAV_MARKERS = (
    "sign in",
    "join now",
    "my network",
    "notifications",
    "messaging",
    "privacy policy",
    "user agreement",
    "help center",
)

# JS: locate the visible job-description area. Prefers a heading "About the
# job" and climbs to a container that holds the description markup; falls back
# to known description-content containers. Avoids deep generated class chains.
_FIND_DESCRIPTION_JS = r"""() => {
  const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4'));
  for (const heading of headings) {
    const label = (heading.innerText || '').trim().toLowerCase();
    if (label.includes('about the job')) {
      let node = heading.parentElement;
      for (let i = 0; i < 6 && node; i++) {
        const textLen = (node.innerText || '').length;
        if (textLen > 100 && node.querySelector('p, li, div[class*="markup"], br')) {
          return node;
        }
        node = node.parentElement;
      }
      return heading.parentElement;
    }
  }
  const containers = Array.from(document.querySelectorAll(
    'div[class*="jobs-description__content"], ' +
    'div[class*="show-more-less-html__markup"], ' +
    'section[class*="job-description"], div[class*="job-description"]'
  ));
  for (const el of containers) {
    if ((el.innerText || '').length > 100) return el;
  }
  return null;
}"""


@dataclass
class LinkedInJobDescription:
    """Full current job description for one LinkedIn vacancy."""

    external_id: str
    raw_text: str
    markdown: str | None
    source_url: str


def canonical_job_url(external_id: str) -> str:
    """Canonical LinkedIn job URL for an external id (no tracking params)."""
    return LINKEDIN_JOB_VIEW_URL.format(external_id=external_id)


def is_valid_external_id(external_id: str) -> bool:
    """True if the external id is non-empty and numeric."""
    return bool(external_id) and external_id.isdigit()


def normalize_job_description(text: str) -> str:
    """Normalize job-description text.

    - ``\\r\\n`` and ``\\r`` are converted to ``\\n``;
    - leading/trailing whitespace is trimmed;
    - trailing whitespace on each line is trimmed;
    - three or more consecutive blank lines collapse to two.

    Text is otherwise preserved unchanged (no lowercase, no rewriting).
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]

    normalized: list[str] = []
    blank_streak = 0
    for line in lines:
        if not line.strip():
            blank_streak += 1
            if blank_streak <= 2:
                normalized.append("")
        else:
            blank_streak = 0
            normalized.append(line)

    while normalized and not normalized[0]:
        normalized.pop(0)
    while normalized and not normalized[-1]:
        normalized.pop()
    return "\n".join(normalized)


def calculate_content_hash(text: str) -> str:
    """SHA-256 of the normalized text as a lowercase 64-char hex string."""
    normalized = normalize_job_description(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def to_conservative_markdown(text: str) -> str | None:
    """Convert normalized description text to conservative Markdown.

    Paragraph and list separation is preserved; visible bullet markers are
    converted consistently to "- ". Headings are not inferred and content is
    not rewritten. Returns None for empty input.
    """
    normalized = normalize_job_description(text)
    if not normalized:
        return None

    md_lines: list[str] = []
    for line in normalized.split("\n"):
        stripped = line.strip()
        if not stripped:
            md_lines.append("")
            continue
        if stripped[0] in ("•", "·", "–", "-", "*"):
            rest = stripped[1:].lstrip()
            md_lines.append(f"- {rest}")
        else:
            md_lines.append(stripped)

    return normalize_job_description("\n".join(md_lines))


def validate_job_description(external_id: str, text: str) -> None:
    """Raise ValueError if the extracted text is not a usable description."""
    if not text or not text.strip():
        raise ValueError(f"empty job description for external_id {external_id}")
    if len(text) < _MIN_DESCRIPTION_CHARS:
        raise ValueError(
            f"job description too short for external_id {external_id} "
            f"({len(text)} chars)"
        )
    lower = text.lower()
    nav_hits = sum(1 for marker in _NAV_MARKERS if marker in lower)
    if nav_hits >= 3:
        raise ValueError(
            f"job description looks like page navigation for external_id {external_id}"
        )


def _is_auth_page(url: str) -> bool:
    return any(fragment in url for fragment in _AUTH_FRAGMENTS)


def _click_show_more(page, root) -> None:
    """Click a 'Show more' button inside the description area once, if present."""
    for button in root.query_selector_all("button"):
        label = " ".join((button.inner_text() or "").split()).lower()
        if label == "show more":
            try:
                button.scroll_into_view_if_needed()
                button.click()
                page.wait_for_timeout(500)
            except Exception:
                pass
            return


def fetch_linkedin_job_description(
    external_id: str,
    storage_state_path: Path,
    debug_pause: bool = False,
) -> LinkedInJobDescription:
    """Fetch the full visible job description for one LinkedIn vacancy.

    Uses the existing authenticated Playwright storage state and the same
    headed Chromium configuration as the LinkedIn collector. Raises a clear
    error when authentication is required or the description cannot be
    validated. Does not click Apply, paginate, or open other vacancies.
    """
    external_id = str(external_id).strip()
    if not is_valid_external_id(external_id):
        raise ValueError(f"invalid LinkedIn external id: {external_id!r}")

    storage_state_path = Path(storage_state_path)
    if not storage_state_path.is_file():
        raise FileNotFoundError(
            f"LinkedIn storage state not found: {storage_state_path}. "
            "Run `python scripts/linkedin_login.py` first to authenticate."
        )

    url = canonical_job_url(external_id)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(storage_state_path))
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")

            if _is_auth_page(page.url) or page.locator("#username").count() > 0:
                raise RuntimeError(
                    "LinkedIn requires authentication. "
                    "Rerun `python scripts/linkedin_login.py`."
                )

            # Wait for the job-description area to become available.
            try:
                page.wait_for_function(_FIND_DESCRIPTION_JS, timeout=10000)
            except Exception:
                pass

            root = page.evaluate_handle(_FIND_DESCRIPTION_JS).as_element()
            if root is None:
                raise ValueError(
                    f"could not locate the job description for external_id {external_id}"
                )

            # Expand a collapsed description once, if LinkedIn shows "Show more".
            _click_show_more(page, root)
            root = page.evaluate_handle(_FIND_DESCRIPTION_JS).as_element()
            if root is None:
                raise ValueError(
                    f"could not locate the job description for external_id {external_id}"
                )

            raw_text = normalize_job_description(root.inner_text())
            validate_job_description(external_id, raw_text)

            if debug_pause:
                print(
                    "Debug pause enabled. Inspect the browser and press Enter to close."
                )
                input()

            return LinkedInJobDescription(
                external_id=external_id,
                raw_text=raw_text,
                markdown=to_conservative_markdown(raw_text),
                source_url=url,
            )
        finally:
            browser.close()
