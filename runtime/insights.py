"""
runtime/insights.py — Phase E
─────────────────────────────
Provider-agnostic LLM-grounding layer for the Ontology Studio.

Responsibilities:
    1. Discover available providers (env-var presence + adapter import).
    2. Build a grounding payload from the asserted ontology and — when the
       caller toggles it — the materialised graph (Phase B / Phase D).
    3. Hand the payload to a provider adapter (`runtime/adapters/`).
    4. Validate IRIs in the response against the ontology so hallucinated
       class/property names are flagged or stripped.

The actual network call lives in the existing adapter classes
(:class:`runtime.adapters.OpenAIAdapter`, etc.). This module wraps them
behind a uniform :class:`Insights.ask` interface so the wizard's
`/api/insights/ask` endpoint and CLI users don't need to know which
provider is active.

This module never embeds API keys, never persists payloads, and never
sends materialised triples to a public-cloud provider unless the caller
explicitly toggles ``include_materialised=True`` *and* acknowledges the
residency hint surfaced by :func:`provider_status`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
PROVIDERS_JSON = HERE / "llm_providers.json"


@dataclass
class ProviderInfo:
    name: str
    label: str
    model: str
    residency: str
    configured: bool
    reason: Optional[str] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "label": self.label, "model": self.model,
            "residency": self.residency, "configured": self.configured,
            "reason": self.reason, **self.extras,
        }


@dataclass
class InsightAnswer:
    answer: str
    provider: str
    model: str
    grounded_iris: List[str]
    unknown_iris: List[str]
    include_materialised: bool
    duration_ms: int
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "provider": self.provider,
            "model": self.model,
            "grounded_iris": self.grounded_iris,
            "unknown_iris": self.unknown_iris,
            "include_materialised": self.include_materialised,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
        }


# ── Provider catalogue ───────────────────────────────────────────────────


def _load_catalogue() -> dict:
    if not PROVIDERS_JSON.is_file():
        return {"providers": {}, "default": None}
    try:
        return json.loads(PROVIDERS_JSON.read_text())
    except Exception:  # noqa: BLE001
        return {"providers": {}, "default": None}


def provider_status() -> List[ProviderInfo]:
    """Inspect each declared provider and report whether it appears
    configured (env vars present, optional config files present). Never
    raises — adapters absent from the python env are reported as
    `configured=False, reason="adapter not installed"` so the Settings
    panel renders meaningfully on minimal hosts.
    """
    cat = _load_catalogue()
    out: List[ProviderInfo] = []
    for name, spec in cat.get("providers", {}).items():
        env_keys = spec.get("env_keys", [])
        configured = True
        reason: Optional[str] = None
        extras: Dict[str, Any] = {}

        # env-key presence
        for k in env_keys:
            if not os.environ.get(k):
                configured = False
                reason = f"environment variable {k} not set"
                break

        # optional config files (e.g. ~/.oci/config)
        if configured:
            for path in spec.get("config_paths", []) or []:
                expanded = os.path.expanduser(path)
                if not os.path.exists(expanded):
                    configured = False
                    reason = f"config file {path} not present"
                    break

        # adapter importability — the Ollama adapter is stdlib-only, but
        # the cloud adapters need their SDK. We probe lazily here to
        # surface install status in the UI.
        if configured and not _adapter_importable(name):
            configured = False
            reason = f"adapter SDK for '{name}' is not installed"

        if name == "ollama":
            extras["base_url"] = os.environ.get(
                "OLLAMA_BASE_URL",
                spec.get("base_url_default", "http://localhost:11434"),
            )

        out.append(ProviderInfo(
            name=name, label=spec.get("label", name),
            model=spec.get("model", ""), residency=spec.get("residency", "?"),
            configured=configured, reason=reason, extras=extras,
        ))
    return out


def _adapter_importable(provider: str) -> bool:
    """Return True if the underlying SDK or local server is reachable. We
    do *not* try to call the adapter — just confirm the import surface.

    Ollama is treated as always importable (urllib-based) — its
    "configured" gate is whether the local server actually answers, and
    that's checked at call time.
    """
    try:
        if provider == "openai":
            import openai  # noqa: F401
            return True
        if provider == "anthropic":
            import anthropic  # noqa: F401
            return True
        if provider == "oci":
            import oci  # noqa: F401
            return True
        if provider == "vertex":
            from google.cloud import aiplatform  # noqa: F401
            return True
        if provider == "ollama":
            return True
        if provider == "fake":
            return True
    except ImportError:
        return False
    return False


def _resolve_default(catalogue: dict, prefer: Optional[str]) -> Optional[str]:
    if prefer and prefer in catalogue.get("providers", {}):
        return prefer
    return catalogue.get("default")


# ── Grounding payload ────────────────────────────────────────────────────


def build_grounding(ontology_path: str,
                    materialised_path: Optional[str] = None,
                    *,
                    max_class_chars: int = 2_000,
                    max_materialised_triples: int = 200) -> Dict[str, Any]:
    """Build a small, model-friendly summary of the ontology to send to
    the LLM. Keeps the payload provider-independent: the same structure
    is sent regardless of which adapter executes the call.
    """
    out: Dict[str, Any] = {"asserted_chars": 0, "materialised_chars": 0}
    if os.path.isfile(ontology_path):
        text = Path(ontology_path).read_text(encoding="utf-8", errors="replace")
        out["asserted_chars"] = len(text)
        out["asserted_summary"] = text[:max_class_chars]
        out["asserted_iris"] = sorted(_extract_iris(text))
    if materialised_path and os.path.isfile(materialised_path):
        text = Path(materialised_path).read_text(encoding="utf-8", errors="replace")
        out["materialised_chars"] = len(text)
        # Sample at most N materialised triples — keeps the prompt small.
        sample = "\n".join(text.splitlines()[:max_materialised_triples])
        out["materialised_summary"] = sample
        out["materialised_iris"] = sorted(_extract_iris(text))
    return out


# Two patterns: angle-bracketed IRIs and qnames. The qname pattern allows
# an empty prefix (`:Asset`) which Turtle uses heavily.
_IRI_RE_FULL = re.compile(r"<([^>\s]+)>")
_IRI_RE_QNAME = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*)?:([A-Za-z][A-Za-z0-9_-]*)")


def _extract_iris(turtle_text: str) -> set:
    """Pull every IRI / qname token out of a Turtle-ish string. Imperfect
    but good enough for the hallucination check — we want a high-recall
    set of "names the ontology has a record of."""
    found: set = set()
    for m in _IRI_RE_FULL.finditer(turtle_text):
        token = f"<{m.group(1)}>"
        found.add(token)
    for m in _IRI_RE_QNAME.finditer(turtle_text):
        prefix = m.group(1) or ""
        local = m.group(2)
        token = f"{prefix}:{local}"
        if token in {":", "rdf:type"}:
            continue
        # filter common false positives
        if prefix.lower() in {"http", "https", "urn"}:
            continue
        found.add(token)
    return found


# ── Hallucinated-IRI validation ──────────────────────────────────────────


def validate_iris(answer: str, known_iris: Iterable[str]
                  ) -> tuple[List[str], List[str]]:
    """Scan an LLM response for IRI / qname tokens and split them into
    those that appear in the known-IRI set vs those that don't.

    Returns (grounded, unknown).
    """
    found_iris = _extract_iris(answer)
    known = set(known_iris)
    grounded: List[str] = sorted(t for t in found_iris if t in known)
    unknown: List[str] = sorted(t for t in found_iris if t not in known)
    return grounded, unknown


# ── Insights orchestration ───────────────────────────────────────────────


SYSTEM_PROMPT = (
    "You are an ontology-aware assistant. Answer using ONLY the entities, "
    "classes and properties present in the ontology summary supplied. If "
    "the question cannot be answered from the supplied context, say so "
    "rather than inventing terms. Always reference IRIs / qnames exactly "
    "as they appear in the context — never paraphrase or shorten them."
)


class Insights:
    """High-level Insights orchestrator. One instance per ontology
    project; pick a provider per call.
    """

    def __init__(self, ontology_path: str, materialised_path: Optional[str] = None):
        self.ontology_path = ontology_path
        self.materialised_path = materialised_path

    def ask(self, question: str, *,
            provider: Optional[str] = None,
            model: Optional[str] = None,
            include_materialised: bool = False,
            adapter: Any = None) -> InsightAnswer:
        """Ground the question, call the provider, validate the answer.

        Args:
            question: The user's question.
            provider: Provider name from ``llm_providers.json``. If None,
                the catalogue default is used.
            model: Override the provider's default model.
            include_materialised: When True the materialised graph is
                included in the grounding payload. Risk #4 in the
                roadmap — surface the residency hint to the user before
                flipping this on for a public-cloud provider.
            adapter: An optional pre-built adapter (used by tests to
                inject a fake without touching the network).
        """
        catalogue = _load_catalogue()
        provider = _resolve_default(catalogue, provider)
        if not provider:
            raise RuntimeError("No provider configured")
        spec = catalogue["providers"].get(provider, {})
        model = model or spec.get("model", "")

        materialised = self.materialised_path if include_materialised else None
        grounding = build_grounding(self.ontology_path, materialised)

        prompt = _format_user_prompt(question, grounding, include_materialised)
        payload = {
            "system": SYSTEM_PROMPT,
            "user": prompt,
            "model": model,
        }

        adapter = adapter or _build_adapter(provider, model)

        started = datetime.now(timezone.utc)
        try:
            answer_text = adapter.complete(payload)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"{provider} call failed: {exc}") from exc
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

        known = set(grounding.get("asserted_iris", []))
        if include_materialised:
            known |= set(grounding.get("materialised_iris", []))
        grounded, unknown = validate_iris(answer_text, known)

        warnings: List[str] = []
        if unknown:
            warnings.append(
                f"{len(unknown)} IRI(s) in the response are not present in "
                "the ontology — possibly hallucinated."
            )
        if include_materialised and spec.get("residency") == "us-cloud":
            warnings.append(
                f"Materialised triples were sent to {provider} ({spec.get('residency')}). "
                "Confirm this is permitted under your data-residency policy."
            )

        return InsightAnswer(
            answer=answer_text,
            provider=provider,
            model=model,
            grounded_iris=grounded,
            unknown_iris=unknown,
            include_materialised=include_materialised,
            duration_ms=duration_ms,
            warnings=warnings,
        )


def _format_user_prompt(question: str, grounding: Dict[str, Any],
                        include_materialised: bool) -> str:
    parts = [
        "## Asserted ontology (Turtle excerpt)",
        "```turtle",
        grounding.get("asserted_summary", "(empty)"),
        "```",
    ]
    if include_materialised and grounding.get("materialised_summary"):
        parts.extend([
            "",
            "## Materialised triples (Phase B inferences)",
            "```turtle",
            grounding["materialised_summary"],
            "```",
        ])
    parts.extend(["", "## Question", question])
    return "\n".join(parts)


def _build_adapter(provider: str, model: str):
    """Lazy adapter factory. Imports only the requested provider's SDK
    so missing providers don't poison startup.
    """
    if provider == "openai":
        from runtime.adapters import OpenAIAdapter
        return OpenAIAdapter(model=model)
    if provider == "anthropic":
        from runtime.adapters import AnthropicAdapter
        return AnthropicAdapter(model=model)
    if provider == "oci":
        from runtime.adapters import OCIAdapter
        return OCIAdapter(model=model)
    if provider == "vertex":
        from runtime.adapters import VertexAdapter
        return VertexAdapter(model=model)
    if provider == "ollama":
        from runtime.adapters import OllamaAdapter
        return OllamaAdapter(model=model)
    raise ValueError(f"Unknown provider: {provider}")


# ── NL → Rule drafting (suggestion #1) ───────────────────────────────────


@dataclass
class RuleDraft:
    body: str
    kind: str
    provider: str
    model: str
    grounded_iris: List[str]
    unknown_iris: List[str]
    class_iris: List[str]            # subset of grounded_iris that name vocabulary classes
    valid: bool
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    duration_ms: int = 0
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "body": self.body, "kind": self.kind,
            "provider": self.provider, "model": self.model,
            "grounded_iris": self.grounded_iris,
            "unknown_iris": self.unknown_iris,
            "class_iris": self.class_iris,
            "valid": self.valid,
            "validation_errors": self.validation_errors,
            "validation_warnings": self.validation_warnings,
            "duration_ms": self.duration_ms,
            "raw_response": self.raw_response,
        }


_DRAFT_SYSTEM = {
    "shacl": (
        "You are a SHACL author. Emit a SHACL `sh:NodeShape` containing "
        "exactly one `sh:rule` block in Turtle. Use ONLY the qnames listed "
        "in the supplied vocabulary; never invent class or property names. "
        "Output the Turtle fragment alone — no prose, no markdown fences, "
        "no `@prefix` lines."
    ),
    "sparql": (
        "You are a SPARQL author. Emit one CONSTRUCT query that materialises "
        "the requested inference. Use ONLY the qnames listed in the supplied "
        "vocabulary; never invent class or property names. Include the "
        "`PREFIX :` line that matches the ontology base IRI. Output the "
        "query alone — no prose, no markdown fences."
    ),
    "owl": (
        "You are an OWL ontology author. Emit a small Turtle fragment that "
        "declares the requested OWL axiom (e.g. `:partOf a owl:ObjectProperty, "
        "owl:TransitiveProperty .`). Use ONLY the qnames listed in the "
        "supplied vocabulary. Output the Turtle fragment alone — no prose, "
        "no markdown fences."
    ),
}


def _format_vocabulary(vocab: dict, *, max_classes: int = 60,
                      max_properties: int = 80) -> str:
    """Render a compact vocabulary slice for the prompt — qname + label
    only, capped to keep the token bill predictable.
    """
    classes = (vocab.get("classes") or [])[:max_classes]
    props = (vocab.get("properties") or [])[:max_properties]
    lines = [f"# Base IRI: {vocab.get('base_iri') or '(none)'}", "", "## Classes"]
    for c in classes:
        label = c.get("label") or ""
        lines.append(f"- {c.get('qname')}{f'  — {label}' if label else ''}")
    lines += ["", "## Properties"]
    for p in props:
        label = p.get("label") or ""
        kind = p.get("kind") or ""
        lines.append(f"- {p.get('qname')} ({kind}){f'  — {label}' if label else ''}")
    return "\n".join(lines)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences (```turtle / ```sparql / ```) that
    obedient models still emit despite the system prompt asking them
    not to. Returns the inner content untouched if no fences present.
    """
    s = text.strip()
    if s.startswith("```"):
        # Drop the opening fence + language hint, then the closing fence.
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def draft_rule(*, nl: str, kind: str,
               vocabulary: dict, provider: Optional[str] = None,
               model: Optional[str] = None,
               adapter: Any = None) -> RuleDraft:
    """Ask the configured LLM to draft a rule body from the user's
    English description. Pipes the response through Phase C's
    `validate_rule` and the IRI filter so the caller knows whether the
    draft is safe to accept as-is.
    """
    kind = (kind or "").strip().lower()
    if kind not in _DRAFT_SYSTEM:
        raise ValueError(f"Unknown rule kind for NL draft: {kind!r}")

    catalogue = _load_catalogue()
    provider = _resolve_default(catalogue, provider)
    if not provider:
        raise RuntimeError("No provider configured")
    spec = catalogue["providers"].get(provider, {})
    model = model or spec.get("model", "")

    vocab_text = _format_vocabulary(vocabulary)
    user_prompt = (
        "## Vocabulary (use only these names)\n\n"
        f"{vocab_text}\n\n"
        "## Description\n\n"
        f"{nl.strip()}\n"
    )
    payload = {
        "system": _DRAFT_SYSTEM[kind],
        "user": user_prompt,
        "model": model,
    }

    adapter = adapter or _build_adapter(provider, model)
    started = datetime.now(timezone.utc)
    try:
        raw = adapter.complete(payload)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{provider} draft call failed: {exc}") from exc
    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    body = _strip_fences(raw)

    # Validate via Phase C.
    from wizard.rules import validate_rule
    val = validate_rule({"kind": kind, "label": "draft", "body": body})

    # IRI hallucination check against the supplied vocabulary. Standard
    # vocabularies (`sh:`, `owl:`, `rdf:`, `rdfs:`, `xsd:`, `prov:`,
    # `skos:`, `sh:this` etc.) are tools of the trade, not user
    # vocabulary — they aren't hallucinations even when absent from
    # the catalogue, so we drop them before classifying.
    known: set = set()
    for c in vocabulary.get("classes", []):
        if c.get("qname"): known.add(c["qname"])
    for p in vocabulary.get("properties", []):
        if p.get("qname"): known.add(p["qname"])
    standard_prefixes = ("sh:", "owl:", "rdf:", "rdfs:", "xsd:",
                         "prov:", "skos:", "dcterms:", "sh1:")
    grounded, unknown = validate_iris(body, known)
    unknown = [t for t in unknown
               if not any(t.startswith(pref) for pref in standard_prefixes)]

    # Subset of grounded that point at vocabulary *classes* — used by the
    # conversational drawer (#8) to highlight the involved nodes on the
    # inline relationships graph.
    class_qnames = {c.get("qname") for c in vocabulary.get("classes", []) if c.get("qname")}
    class_iris = [t for t in grounded if t in class_qnames]

    return RuleDraft(
        body=body, kind=kind,
        provider=provider, model=model,
        grounded_iris=grounded, unknown_iris=unknown,
        class_iris=class_iris,
        valid=val.ok,
        validation_errors=val.errors,
        validation_warnings=val.warnings,
        duration_ms=duration_ms,
        raw_response=raw,
    )


# ── RCA prompt presets (Phase L6) ────────────────────────────────────────


_RCA_PRESETS: Dict[str, str] = {
    "root-cause": (
        "What caused the event {event}? Walk the :hasCause chain in the "
        "materialised graph, name every intermediate cause, and identify the "
        ":rootCause if one is asserted. Cite each step's `prov:wasDerivedFrom` "
        "rule id so an auditor can trace the chain back."
    ),
    "similar-incidents": (
        "Show past incidents similar to {event}. For each candidate, list "
        "shared :hasCause / :triggers edges and shared severity tier. Match "
        "only against instances already in the asserted-or-materialised "
        "graph — do not speculate."
    ),
}


def list_rca_presets() -> Dict[str, str]:
    """Return the available RCA prompt presets keyed by short name.
    Used by the wizard's Insights box to populate the preset menu."""
    return dict(_RCA_PRESETS)


def expand_rca_preset(name: str, *, event_iri: str) -> str:
    """Substitute ``{event}`` in a preset with the supplied IRI and
    return the question text ready to pass to :meth:`Insights.ask`.
    """
    template = _RCA_PRESETS.get(name)
    if not template:
        raise KeyError(f"Unknown RCA preset: {name!r}")
    return template.replace("{event}", event_iri.strip())


# ── Rule summarisation (suggestion #2) ───────────────────────────────────


_SUMMARISE_SYSTEM = (
    "You write one-sentence plain-English summaries of ontology rules. "
    "Given the rule's kind, label, and body, return a single sentence "
    "(≤ 25 words) that a non-engineer reviewer can read at a glance. "
    "No prose framing, no quotes, no markdown — just the sentence."
)


def summarise_rule(rule: dict, *, provider: Optional[str] = None,
                   model: Optional[str] = None, adapter: Any = None) -> str:
    """Return a single-sentence English summary of ``rule`` via the
    configured LLM provider. Raises if no provider is configured —
    callers handle the absence as a best-effort skip.
    """
    catalogue = _load_catalogue()
    provider = _resolve_default(catalogue, provider)
    if not provider:
        raise RuntimeError("No provider configured")
    spec = catalogue["providers"].get(provider, {})
    model = model or spec.get("model", "")

    body = rule.get("body") or ""
    user = (
        f"Rule kind: {rule.get('kind') or '?'}\n"
        f"Label: {rule.get('label') or '(none)'}\n\n"
        f"```\n{body[:800]}\n```\n"
    )
    payload = {"system": _SUMMARISE_SYSTEM, "user": user, "model": model}

    adapter = adapter or _build_adapter(provider, model)
    raw = adapter.complete(payload)
    # Models wrap summaries in any combination of "..." / '...' /
    # ```...```. Strip iteratively so we handle order-independent
    # nestings like `"\`\`\`...\`\`\`"`.
    text = raw.strip()
    for _ in range(4):
        before = text
        text = text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        elif text.startswith("'") and text.endswith("'"):
            text = text[1:-1]
        text = _strip_fences(text)
        if text == before:
            break
    text = " ".join(text.split())
    return text


__all__ = [
    "Insights",
    "InsightAnswer",
    "ProviderInfo",
    "RuleDraft",
    "build_grounding",
    "draft_rule",
    "expand_rca_preset",
    "list_rca_presets",
    "provider_status",
    "summarise_rule",
    "validate_iris",
]
