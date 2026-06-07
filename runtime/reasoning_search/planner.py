"""Planner: NL question → ontology-validated query plan (§11 #6).

The LLM is constrained to a **controlled vocabulary** (the flavor's OWL classes +
context terms). Any class/property it returns that isn't in the vocabulary is
rejected — this is the core guardrail that stops the model inventing entities or
columns. Phase 0 covers single-hop plans; ``hops`` is reserved for MVP-2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .structured_output import Adapter, complete_json

_ALLOWED_OPS = {"=", "!=", ">", "<", ">=", "<=", "like"}


class PlanValidationError(ValueError):
    """The plan referenced terms outside the ontology vocabulary."""


@dataclass
class Filter:
    prop: str
    op: str
    value: object


@dataclass
class Plan:
    intent: str
    classes: list[str]
    filters: list[Filter] = field(default_factory=list)
    hops: list[dict] = field(default_factory=list)   # reserved for multi-hop (MVP-2)
    raw: dict = field(default_factory=dict)

    @property
    def primary_class(self) -> str:
        return self.classes[0]


_SYSTEM = (
    "You are a query planner for an ontology-grounded search engine. "
    "You translate a question into a STRICT JSON plan over a fixed vocabulary. "
    "You may ONLY use class and property names from the provided vocabulary — "
    "never invent names. Reply with a JSON object only."
)


def _build_user(question: str, vocab: list[str]) -> str:
    return (
        f"Vocabulary (allowed class/property names): {sorted(vocab)}\n\n"
        f"Question: {question!r}\n\n"
        "Return JSON: {\"intent\": str, \"classes\": [str, ...], "
        "\"filters\": [{\"prop\": str, \"op\": one of "
        f"{sorted(_ALLOWED_OPS)}, \"value\": str|number}}, ...]}}. "
        "Use the single most relevant class first. Only include filters you can "
        "justify from the question."
    )


def plan(question: str, *, vocab: set[str], adapter: Adapter) -> Plan:
    """Produce a validated `Plan`, or raise `PlanValidationError`.

    Args:
        question: the user's NL question.
        vocab: allowed class/property names (see `_loaders.controlled_vocab`).
        adapter: anything with ``complete(payload) -> str``.
    """
    if not vocab:
        raise PlanValidationError("empty vocabulary — is the flavor configured?")

    obj = complete_json(
        adapter,
        system=_SYSTEM,
        user=_build_user(question, list(vocab)),
        required_keys=("intent", "classes"),
        token_budget=512,
    )

    classes = [c for c in (obj.get("classes") or []) if isinstance(c, str)]
    if not classes:
        raise PlanValidationError("plan named no classes")

    # Guardrail: every class must be in the ontology vocabulary.
    unknown = [c for c in classes if c not in vocab]
    if unknown:
        raise PlanValidationError(f"plan referenced unknown classes: {unknown}")

    filters: list[Filter] = []
    for f in obj.get("filters") or []:
        if not isinstance(f, dict):
            continue
        prop, op = f.get("prop"), f.get("op")
        if prop not in vocab:
            raise PlanValidationError(f"filter referenced unknown property: {prop!r}")
        if op not in _ALLOWED_OPS:
            raise PlanValidationError(f"filter used unsupported op: {op!r}")
        filters.append(Filter(prop=prop, op=op, value=f.get("value")))

    return Plan(
        intent=str(obj.get("intent", "")),
        classes=classes,
        filters=filters,
        hops=obj.get("hops") or [],
        raw=obj,
    )
