"""Tests for the career asset registry."""

import pytest
from docx import Document

from app.career.assets import CareerAsset, CareerAssetType
from app.career.registry import (
    CareerAssetPaths,
    CareerAssetRegistry,
    load_career_asset_registry,
)
from app.llm.errors import MissingCareerAssetError

BRIEF = CareerAssetType.MASTER_CAREER_BRIEF
SCORING = CareerAssetType.SCORING_RULES
RESUME = CareerAssetType.MASTER_RESUME


def _long_text(seed: str) -> str:
    return (
        f"{seed} with enough words to exceed the loader minimum and stay "
        "distinct for assertions across the registry tests."
    )


def _make_docx(path, text):
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))


def _brief_path(tmp_path):
    path = tmp_path / "brief.docx"
    _make_docx(path, _long_text("Master career brief"))
    return path


def _scoring_path(tmp_path):
    path = tmp_path / "scoring.md"
    path.write_text(_long_text("Scoring rules"), encoding="utf-8")
    return path


def test_master_brief_is_required_when_not_configured(tmp_path):
    with pytest.raises(MissingCareerAssetError):
        load_career_asset_registry(CareerAssetPaths(master_career_brief=None))


def test_master_brief_is_required_when_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_career_asset_registry(
            CareerAssetPaths(master_career_brief=tmp_path / "missing.docx")
        )


def test_optional_assets_may_be_absent(tmp_path):
    registry = load_career_asset_registry(
        CareerAssetPaths(master_career_brief=_brief_path(tmp_path))
    )

    assert registry.has(BRIEF)
    assert not registry.has(SCORING)
    assert registry.get_optional(SCORING) is None


def test_configured_assets_load_once(tmp_path):
    registry = load_career_asset_registry(
        CareerAssetPaths(
            master_career_brief=_brief_path(tmp_path),
            scoring_rules=_scoring_path(tmp_path),
        )
    )

    assert registry.has(BRIEF)
    assert registry.has(SCORING)
    assert len(registry.assets) == 2


def test_metadata_does_not_include_private_text(tmp_path):
    brief_text = _long_text("Secret brief wording")
    brief = _brief_path(tmp_path)
    _make_docx(brief, brief_text)
    registry = load_career_asset_registry(
        CareerAssetPaths(master_career_brief=brief)
    )

    metadata = registry.metadata()

    assert len(metadata) == 1
    item = metadata[0]
    assert set(item) == {
        "asset_type",
        "filename",
        "source_format",
        "content_hash",
        "character_count",
    }
    assert item["asset_type"] == BRIEF.value
    assert item["filename"] == "brief.docx"
    assert item["source_format"] == "docx"
    assert brief_text not in str(item)


def test_required_and_optional_getters(tmp_path):
    asset = CareerAsset(
        asset_type=BRIEF,
        source_path=tmp_path / "brief.docx",
        source_format="docx",
        text=_long_text("brief"),
        content_hash="h" * 64,
        character_count=150,
    )
    registry = CareerAssetRegistry(assets={BRIEF: asset})

    assert registry.get_required(BRIEF) is asset
    assert registry.get_optional(BRIEF) is asset
    assert registry.get_optional(SCORING) is None

    with pytest.raises(MissingCareerAssetError):
        registry.get_required(RESUME)
