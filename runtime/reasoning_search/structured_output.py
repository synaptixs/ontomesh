"""Provider-agnostic structured (JSON) output for reasoning search (§11 #5).

Wraps any LLM adapter exposing ``complete(payload: dict) -> str`` (the project's
``BaseAdapter`` interface, and any duck-typed fake) and coerces the response into
a validated JSON object: strips code fences, parses, checks required keys, and
retries once with a corrective instruction on failure.

No external schema library — validation is a light required-keys/type check so
the module stays dependency-free and unit-testable offline with a fake adapter.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Protocol


class Adapter(Protocol):
    """Minimal structural type — anything with ``complete(payload) -> str``."""

    def complete(self, payload: dict) -> str: ...  # noqa: E704


class StructuredOutputError(ValueError):
    """Raised when the model cannot be coerced into valid JSON after retries."""


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """Best-effort: parse JSON, tolerating ```code fences``` and prose around it."""
    if not text or not text.strip():
        raise StructuredOutputError("empty model response")
    candidate = text.strip()
    m = _FENCE.search(candidate)
    if m:
        candidate = m.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Fall back to the first {...} or [...] block in the text.
        start = min(
            (i for i in (candidate.find("{"), candidate.find("[")) if i != -1),
            default=-1,
        )
        if start != -1:
            for end in range(len(candidate), start, -1):
                try:
                    return json.loads(candidate[start:end])
                except json.JSONDecodeError:
                    continue
        raise StructuredOutputError("response was not valid JSON")


def _build_payload(system: str, user: str, token_budget: int) -> dict:
    return {
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "token_budget": token_budget,
        "payload_id": "reasoning-search",
    }


def complete_json(
    adapter: Adapter,
    *,
    system: str,
    user: str,
    required_keys: Iterable[str] = (),
    token_budget: int = 1024,
    max_retries: int = 1,
) -> dict:
    """Call ``adapter`` and return a validated JSON object.

    Args:
        adapter: object with ``complete(payload) -> str``.
        system / user: prompt parts.
        required_keys: keys the returned object must contain.
        token_budget: hint passed through in the payload.
        max_retries: extra attempts after the first, with a corrective nudge.

    Raises:
        StructuredOutputError: if no valid object is produced.
    """
    required = list(required_keys)
    user_msg = user
    last_err = ""
    for attempt in range(max_retries + 1):
        raw = adapter.complete(_build_payload(system, user_msg, token_budget))
        try:
            obj = _extract_json(raw)
            if not isinstance(obj, dict):
                raise StructuredOutputError("expected a JSON object")
            missing = [k for k in required if k not in obj]
            if missing:
                raise StructuredOutputError(f"missing required keys: {missing}")
            return obj
        except StructuredOutputError as exc:
            last_err = str(exc)
            user_msg = (
                f"{user}\n\nYour previous reply was invalid ({last_err}). "
                f"Reply with ONLY a JSON object containing keys: {required}."
            )
    raise StructuredOutputError(f"failed after {max_retries + 1} attempts: {last_err}")
