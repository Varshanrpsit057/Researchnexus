"""One repair retry when structured LLM output fails Pydantic validation
(Architecture §7: "JSON mode/function-calling -> Pydantic validate -> one
schema_repair retry"; Roadmap Task 1 item 5 -- generic machinery every
future LLM-structured call reuses; no business prompts yet).
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def parse_structured(raw_output: str, schema: type[T]) -> T:
    return schema.model_validate(json.loads(raw_output))


def build_repair_messages(
    original_messages: list[dict[str, str]],
    raw_output: str,
    error: Exception,
    schema: type[BaseModel],
) -> list[dict[str, str]]:
    repair_instruction = (
        "Your previous response could not be parsed as valid JSON matching the "
        f"required schema. Schema: {schema.model_json_schema()}. "
        f"Validation error: {error}. Previous response: {raw_output}. "
        "Return ONLY corrected JSON matching the schema -- no prose, no markdown fences."
    )
    return [
        *original_messages,
        {"role": "assistant", "content": raw_output},
        {"role": "user", "content": repair_instruction},
    ]
