"""Eval harness for reasoning search (§11 #16).

Runs a set of questions through the engine and scores each on cheap, objective
signals — **exec-success**, **groundedness** (non-empty, cited answer), and
**status** — then aggregates. The natural eval set is the project's **competency
questions** (the questions the ontology is meant to answer); pass them in as a
list, or any question set.

The ``run`` callable is injected so this works with a live provider in CI/local
or with a fake adapter in unit tests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable


@dataclass
class CaseResult:
    question: str
    status: str
    exec_ok: bool       # query executed (or gracefully empty), not ungrounded/blocked
    grounded: bool      # non-empty answer
    cited: bool         # at least one citation
    confidence: float


def evaluate(questions: list[str], *, run: Callable[[str], object]) -> list[CaseResult]:
    """Score each question. ``run`` returns a ``ReasonedAnswer``-like object."""
    out: list[CaseResult] = []
    for q in questions:
        ans = run(q)
        status = getattr(ans, "status", "ok")
        out.append(CaseResult(
            question=q,
            status=status,
            exec_ok=status in ("ok", "empty"),
            grounded=bool(getattr(ans, "answer", "").strip()),
            cited=bool(getattr(ans, "citations", [])),
            confidence=float(getattr(ans, "confidence", 0.0)),
        ))
    return out


def summarize(results: list[CaseResult]) -> dict:
    """Aggregate rates for a CI gate / report."""
    n = len(results) or 1
    return {
        "n": len(results),
        "exec_rate": sum(r.exec_ok for r in results) / n,
        "grounded_rate": sum(r.grounded for r in results) / n,
        "cited_rate": sum(r.cited for r in results) / n,
        "avg_confidence": sum(r.confidence for r in results) / n,
        "cases": [asdict(r) for r in results],
    }
