"""Provider-neutral career asset types and immutable asset objects."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CareerAssetType(str, Enum):
    """Kinds of private career documents Statera can load."""

    MASTER_CAREER_BRIEF = "master_career_brief"
    MASTER_RESUME = "master_resume"
    RESUME_TEMPLATE = "resume_template"
    APPLICATION_RULES = "application_rules"
    SCORING_RULES = "scoring_rules"


@dataclass(frozen=True)
class CareerAsset:
    """A normalized, provider-neutral career document.

    ``text`` holds the complete normalized extracted content. The original
    binary file is never stored on the object. ``repr`` intentionally omits
    the text so that logging an asset cannot leak private content.
    """

    asset_type: CareerAssetType
    source_path: Path
    source_format: str
    text: str
    content_hash: str
    character_count: int

    def __repr__(self) -> str:
        return (
            "CareerAsset("
            f"asset_type={self.asset_type.value!r}, "
            f"source_path={str(self.source_path)!r}, "
            f"source_format={self.source_format!r}, "
            f"content_hash={self.content_hash!r}, "
            f"character_count={self.character_count!r})"
        )
