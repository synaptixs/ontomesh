"""Runtime reasoner — derive facts over the query-result subgraph (§11 #20).

A small, dependency-free forward-chaining (Datalog-style) engine. Given a set of
ground **facts** (built from the records a search retrieved, plus relationship
edges) and a set of **rules** (Horn clauses), it computes the least fixpoint and
returns the **derived** facts — each with `prov:wasDerivedFrom`-style lineage
(which rule fired and which facts supported it).

This is what turns retrieval into *reasoning*: e.g.

    impacts(?c) :- consumes(?c, ?s), hosts(?r, ?s), degraded(?r)

derives `impacts(acme)` from relationship + status facts that never stored
"impacted" anywhere. Multi-hop conclusions fall out of chaining rules over the
relationship facts.

Facts/atoms are tuples: ``(predicate, arg1, arg2, ...)``. In rule atoms, a term
beginning with ``?`` is a variable; everything else is a constant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

Fact = tuple[str, ...]
Atom = tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    head: Atom
    body: tuple[Atom, ...]
    name: str = ""


@dataclass
class ReasonResult:
    facts: set[Fact]                      # all facts (base + derived)
    derived: list[Fact] = field(default_factory=list)
    provenance: dict[Fact, tuple[str, tuple[Fact, ...]]] = field(default_factory=dict)


# ── rule parsing ─────────────────────────────────────────────────────────────
_ATOM = re.compile(r"([A-Za-z_]\w*)\s*\(([^)]*)\)")


def _strip_quotes(term: str) -> str:
    """Strip surrounding quotes from a constant term (variables have none)."""
    if len(term) >= 2 and term[0] in "\"'" and term[-1] == term[0]:
        return term[1:-1]
    return term


def _parse_atom(s: str) -> Atom:
    m = _ATOM.fullmatch(s.strip())
    if not m:
        raise ValueError(f"bad atom: {s!r}")
    pred = m.group(1)
    args = [_strip_quotes(a.strip()) for a in m.group(2).split(",") if a.strip()]
    return (pred, *args)


def parse_rule(text: str, name: str | None = None) -> Rule:
    """Parse ``head(...) :- a(...), b(...)`` into a `Rule`."""
    if ":-" not in text:
        raise ValueError(f"rule needs ':-': {text!r}")
    head_s, body_s = text.split(":-", 1)
    head = _parse_atom(head_s)
    body = tuple(_parse_atom(a.group(0)) for a in _ATOM.finditer(body_s))
    if not body:
        raise ValueError(f"rule has no body: {text!r}")
    return Rule(head=head, body=body, name=name or head[0])


def _is_var(term: str) -> bool:
    return term.startswith("?")


def _unify(atom: Atom, fact: Fact, binding: dict[str, str]) -> dict[str, str] | None:
    if atom[0] != fact[0] or len(atom) != len(fact):
        return None
    b = dict(binding)
    for a, v in zip(atom[1:], fact[1:]):
        if _is_var(a):
            if a in b and b[a] != v:
                return None
            b[a] = v
        elif a != v:
            return None
    return b


def _solve(body: tuple[Atom, ...], facts: set[Fact], binding: dict[str, str]) -> Iterator[dict[str, str]]:
    if not body:
        yield binding
        return
    first, rest = body[0], body[1:]
    for f in facts:
        b = _unify(first, f, binding)
        if b is not None:
            yield from _solve(rest, facts, b)


def _ground(atom: Atom, binding: dict[str, str]) -> Fact:
    return (atom[0], *(binding.get(t, t) if _is_var(t) else t for t in atom[1:]))


def reason(facts, rules: list[Rule], *, max_iter: int = 1000) -> ReasonResult:
    """Forward-chain ``rules`` over ``facts`` to a fixpoint.

    Returns a `ReasonResult` whose ``derived`` lists only the *newly inferred*
    facts (not the base facts), each keyed in ``provenance`` to the rule that
    fired and the supporting facts.
    """
    known: set[Fact] = {tuple(f) for f in facts}
    prov: dict[Fact, tuple[str, tuple[Fact, ...]]] = {}
    for _ in range(max_iter):
        fresh: set[Fact] = set()
        for rule in rules:
            for binding in _solve(rule.body, known, {}):
                head = _ground(rule.head, binding)
                if head not in known and head not in fresh:
                    fresh.add(head)
                    prov[head] = (rule.name, tuple(_ground(a, binding) for a in rule.body))
        if not fresh:
            break
        known |= fresh
    return ReasonResult(facts=known, derived=list(prov.keys()), provenance=prov)
