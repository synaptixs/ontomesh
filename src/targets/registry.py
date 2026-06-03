"""
src/targets/registry.py — T1.5
──────────────────────────────
Target registry + multi-target dispatcher.

Why a registry?
  - Keeps the CLI's ``--targets cypher,graphql,detection_rules``
    parsing local to one map.
  - Lets the test suite enumerate every shipped target without
    importing each module by hand.
  - Gives future targets (Snowflake / Pydantic / Mermaid / …) a
    single registration point.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .base import GenerationContext, Target, TargetResult
from .cypher import CypherTarget
from .detection_rules import DetectionRulesTarget
from .graphql import GraphQLTarget


# ── Registry ─────────────────────────────────────────────────────────────


_BUILTIN_TARGETS: Dict[str, Target] = {
    "cypher":           CypherTarget(),
    "graphql":          GraphQLTarget(),
    "detection_rules":  DetectionRulesTarget(),
}


# Public, kept stable across versions — the CLI's --targets list
# accepts exactly these names. New targets get added here.
AVAILABLE_TARGETS: List[str] = sorted(_BUILTIN_TARGETS.keys())


def get_target(name: str) -> Optional[Target]:
    """Look up a target by name. Returns None for unknown names —
    the dispatcher surfaces them as warnings rather than raising,
    so an unknown flag doesn't break the whole pipeline."""
    return _BUILTIN_TARGETS.get((name or "").strip().lower())


def render_targets(ctx: GenerationContext,
                   *, names: Sequence[str]) -> Dict[str, TargetResult]:
    """Run every named target on the same context. Returns
    ``{target_name: TargetResult}``. Unknown names produce a
    TargetResult with one warning and no files.

    The caller writes the actual files to disk; ``render_targets``
    stays pure for test isolation."""
    out: Dict[str, TargetResult] = {}
    for raw in names or []:
        name = (raw or "").strip().lower()
        if not name:
            continue
        tgt = get_target(name)
        if tgt is None:
            res = TargetResult(target=name)
            res.warnings.append(
                f"unknown target '{name}'; available: "
                f"{', '.join(AVAILABLE_TARGETS)}"
            )
            out[name] = res
            continue
        out[name] = tgt.generate(ctx)
    return out


def write_target_outputs(results: Dict[str, TargetResult],
                          output_dir: str) -> Dict[str, str]:
    """Persist every file emitted by every target under ``output_dir``.
    Returns ``{relative_path: absolute_path}`` so the caller (CLI /
    wizard) can list what was created."""
    import os
    written: Dict[str, str] = {}
    for _name, result in results.items():
        for rel, content in result.files.items():
            abs_path = os.path.join(output_dir, rel)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            written[rel] = abs_path
    return written


__all__ = [
    "AVAILABLE_TARGETS", "get_target", "render_targets",
    "write_target_outputs",
]
