"""Career asset registry: a fixed set of named private documents.

The registry keeps each asset as a separate logical object. It never merges
assets into one uncontrolled string, and its metadata never includes private
text.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.career.assets import CareerAsset, CareerAssetType
from app.career.loaders import load_career_asset
from app.llm.errors import MissingCareerAssetError


@dataclass(frozen=True)
class CareerAssetPaths:
    """Configured paths for each career asset. Optional assets may be None."""

    master_career_brief: Path | None = None
    master_resume: Path | None = None
    resume_template: Path | None = None
    application_rules: Path | None = None
    scoring_rules: Path | None = None


@dataclass(frozen=True)
class CareerAssetRegistry:
    """Loaded career assets keyed by asset type."""

    assets: Mapping[CareerAssetType, CareerAsset]

    def get_required(self, asset_type: CareerAssetType) -> CareerAsset:
        asset = self.assets.get(asset_type)
        if asset is None:
            raise MissingCareerAssetError(
                f"required career asset is not loaded: {asset_type.value}"
            )
        return asset

    def get_optional(self, asset_type: CareerAssetType) -> CareerAsset | None:
        return self.assets.get(asset_type)

    def has(self, asset_type: CareerAssetType) -> bool:
        return asset_type in self.assets

    def metadata(self) -> list[dict[str, object]]:
        """Metadata only; never includes the private asset text."""
        return [
            {
                "asset_type": asset.asset_type.value,
                "filename": asset.source_path.name,
                "source_format": asset.source_format,
                "content_hash": asset.content_hash,
                "character_count": asset.character_count,
            }
            for asset in self.assets.values()
        ]


def _configured_paths(paths: CareerAssetPaths) -> list[tuple[CareerAssetType, Path | None]]:
    return [
        (CareerAssetType.MASTER_CAREER_BRIEF, paths.master_career_brief),
        (CareerAssetType.MASTER_RESUME, paths.master_resume),
        (CareerAssetType.RESUME_TEMPLATE, paths.resume_template),
        (CareerAssetType.APPLICATION_RULES, paths.application_rules),
        (CareerAssetType.SCORING_RULES, paths.scoring_rules),
    ]


def load_career_asset_registry(paths: CareerAssetPaths) -> CareerAssetRegistry:
    """Load configured assets. The Master Career Brief is mandatory.

    Optional assets are loaded only when their path is configured. A configured
    path that is missing raises FileNotFoundError rather than silently skipping.
    """
    loaded: dict[CareerAssetType, CareerAsset] = {}
    seen: set[CareerAssetType] = set()

    for asset_type, path in _configured_paths(paths):
        if asset_type in seen:
            raise ValueError(f"duplicate career asset type: {asset_type.value}")
        seen.add(asset_type)
        if path is None:
            continue
        loaded[asset_type] = load_career_asset(Path(path).expanduser(), asset_type)

    if CareerAssetType.MASTER_CAREER_BRIEF not in loaded:
        raise MissingCareerAssetError(
            "the Master Career Brief is required; set MASTER_CAREER_BRIEF_PATH "
            "to an existing .docx/.md/.txt file."
        )

    return CareerAssetRegistry(assets=loaded)
