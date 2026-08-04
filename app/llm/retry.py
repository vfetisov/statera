"""Provider-neutral corrective retry for structured-output failures.

A single retry is issued only when the model response was not valid structured
output. The retry repeats the complete original request and appends a strict
JSON corrective instruction; it never includes the invalid response or raw
Pydantic details.
"""

from typing import TypeVar

from pydantic import BaseModel

from app.llm.errors import LLMStructuredOutputError
from app.llm.providers.base import LLMMessage, LLMRequest

T = TypeVar("T", bound=BaseModel)

CORRECTIVE_RETRY_INSTRUCTION = (
    "Your previous response could not be accepted as valid structured output "
    "(reason: {reason}).\n"
    "\n"
    "Return exactly one valid JSON object matching the required response schema.\n"
    "\n"
    "Requirements:\n"
    "- Include every required field.\n"
    "- Use the exact allowed field names.\n"
    "- Use integer values for score fields.\n"
    "- Use only an allowed recommendation value.\n"
    "- Use JSON arrays of strings for strengths, weaknesses, and risks.\n"
    "- Do not use Markdown fences.\n"
    "- Do not include commentary before or after the JSON object.\n"
    "- Do not omit fields.\n"
    "- Do not add extra fields.\n"
    "- Ensure all string-length and list-size requirements are satisfied.\n"
)


UNKNOWN_REASON = "unknown_structured_output_error"


def build_structured_output_retry_request(
    original_request: LLMRequest[T],
    error: LLMStructuredOutputError,
) -> LLMRequest[T]:
    """Build one corrective retry request for a structured-output failure.

    Preserves the original model, response model, reasoning effort, task
    metadata, and all original messages (full Master Career Brief and full
    vacancy description included). Appends a single user message with the
    strict-JSON corrective instruction. The invalid provider response is never
    included.
    """
    reason = getattr(error, "reason", UNKNOWN_REASON)
    corrective = LLMMessage(
        role="user",
        content=CORRECTIVE_RETRY_INSTRUCTION.format(reason=reason),
    )
    return LLMRequest(
        messages=original_request.messages + (corrective,),
        response_model=original_request.response_model,
        model=original_request.model,
        reasoning_effort=original_request.reasoning_effort,
        metadata=dict(original_request.metadata),
    )
