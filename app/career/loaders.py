"""Loaders that read private career documents into normalized CareerAssets.

Only document-to-text extraction lives here. No LLM, provider, or SDK imports
are allowed in this module; the resulting assets are provider-neutral.
"""

import hashlib
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.career.assets import CareerAsset, CareerAssetType

MIN_ASSET_CHARACTERS = 100
SUPPORTED_TEXT_EXTENSIONS = (".md", ".txt")


def normalize_asset_text(text: str) -> str:
    """Normalize line endings and blank-line runs without rewriting wording.

    - CRLF and CR are normalized to LF
    - leading and trailing whitespace is removed
    - trailing whitespace on each line is trimmed
    - runs of 3 or more blank lines collapse to 2 blank lines
    - paragraph and list separation is preserved
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run <= 2:
                normalized.append(line)
        else:
            blank_run = 0
            normalized.append(line)
    return "\n".join(normalized).strip()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_asset(
    asset_type: CareerAssetType,
    path: Path,
    source_format: str,
    text: str,
) -> CareerAsset:
    normalized = normalize_asset_text(text)
    if len(normalized) < MIN_ASSET_CHARACTERS:
        raise ValueError(
            f"career asset {path.name} ({asset_type.value}) is only "
            f"{len(normalized)} characters after normalization; expected at "
            f"least {MIN_ASSET_CHARACTERS}."
        )
    return CareerAsset(
        asset_type=asset_type,
        source_path=path,
        source_format=source_format,
        text=normalized,
        content_hash=_content_hash(normalized),
        character_count=len(normalized),
    )


def _iter_docx_blocks(document: Document):
    """Yield text from body paragraphs and table cells in document order."""
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document).text
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                for cell in row.cells:
                    yield cell.text


def load_docx_asset(path: Path, asset_type: CareerAssetType) -> CareerAsset:
    """Extract normalized text from a .docx file (paragraphs + tables)."""
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"career asset not found: {path}")
    if path.suffix.lower() != ".docx":
        raise ValueError(
            f"expected a .docx file for {asset_type.value}, got: {path.name}"
        )
    document = Document(str(path))
    blocks = [
        block for block in _iter_docx_blocks(document) if block and block.strip()
    ]
    return _build_asset(asset_type, path, "docx", "\n".join(blocks))


def load_text_asset(path: Path, asset_type: CareerAssetType) -> CareerAsset:
    """Extract normalized UTF-8 text from a .md or .txt file."""
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"career asset not found: {path}")
    if path.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
        raise ValueError(
            f"unsupported text asset format for {asset_type.value}: "
            f"{path.suffix!r}; supported: {', '.join(SUPPORTED_TEXT_EXTENSIONS)}"
        )
    raw = path.read_text(encoding="utf-8")
    return _build_asset(asset_type, path, path.suffix.lower().lstrip("."), raw)


def load_career_asset(path: Path, asset_type: CareerAssetType) -> CareerAsset:
    """Load a career asset, dispatching by supported file extension."""
    path = Path(path).expanduser()
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return load_docx_asset(path, asset_type)
    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return load_text_asset(path, asset_type)
    raise ValueError(
        f"unsupported career asset format for {asset_type.value}: {suffix!r}; "
        "supported: .docx, .md, .txt"
    )
