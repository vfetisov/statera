"""Check that the configured LLM provider can authenticate and respond.

Sends one minimal structured request through the provider factory. Does not
use the database, career assets, or LinkedIn, and keeps token use minimal.
"""

import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm.providers.base import LLMMessage, LLMRequest  # noqa: E402
from app.llm.providers.factory import create_llm_provider  # noqa: E402


class ProviderStatus(BaseModel):
    """Tiny structured response requested from the provider."""

    status: str


SYSTEM_PROMPT = (
    'Respond with exactly one JSON object with the shape {"status": "ok"} '
    "and nothing else. No Markdown fences, no commentary."
)


def main() -> int:
    try:
        provider = create_llm_provider(settings)
        request = LLMRequest(
            messages=(
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content="Return the status object."),
            ),
            response_model=ProviderStatus,
            model=settings.LLM_MODEL,
            reasoning_effort=settings.LLM_REASONING_EFFORT,
            metadata={"task": "provider_check"},
        )
        result = provider.generate_structured(request)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "provider": getattr(settings, "LLM_PROVIDER", None),
                    "authenticated": False,
                    "request_succeeded": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "provider": result.provider,
                "model": result.model,
                "authenticated": True,
                "request_succeeded": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
