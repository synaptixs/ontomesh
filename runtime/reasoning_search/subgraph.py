"""Materialize the result subgraph as RDF + a minimal live-SPARQL surface.

Turns the rows a search retrieved (plus FK-neighbour edges and reasoner-derived
facts) into subject-centric RDF triples — the *subgraph* that actually backs an
answer. From that we can:

  * export **Turtle** (``to_turtle``) for download / external tools,
  * emit a **nodes/edges** view (``to_view``) for the in-console graph, and
  * run a **minimal SPARQL** ``SELECT`` (basic graph patterns) over it live,
    so a user can interrogate exactly what grounded the answer.

Dependency-free by design: the SPARQL subset is a small conjunctive
basic-graph-pattern matcher with backtracking — no rdflib required.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Triple", "Subgraph", "build_subgraph", "sparql"]


@dataclass(frozen=True)
class Triple:
    s: str
    p: str
    o: str
    o_is_iri: bool = False


@dataclass
class Subgraph:
    triples: list[Triple] = field(default_factory=list)

    # ── exports ────────────────────────────────────────────────────────────
    _RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

    def to_turtle(self, *, base: str = "urn:ontoforge:") -> str:
        lines = ["@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .", ""]
        for t in self.triples:
            s = self._term(t.s, base, iri=True)
            p = "rdf:type" if t.p in ("rdf:type", "a") else self._term(t.p, base, iri=True)
            o = self._term(t.o, base, iri=t.o_is_iri)
            lines.append(f"{s} {p} {o} .")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _term(value: str, base: str, *, iri: bool) -> str:
        if not iri:
            return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
        # Full angle-bracket IRI — unambiguously valid even with '/' in the local part.
        safe = str(value).replace(" ", "%20").replace(">", "%3E")
        return f"<{base}{safe}>"

    def to_view(self) -> dict[str, Any]:
        """Nodes + edges for a graph visualization. Literals become leaf nodes."""
        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        def node(id_: str, kind: str, label: str | None = None) -> None:
            nodes.setdefault(id_, {"id": id_, "kind": kind, "label": label or id_})

        for t in self.triples:
            node(t.s, "entity")
            if t.p in ("rdf:type", "a"):
                node(t.o, "class")
                edges.append({"from": t.s, "to": t.o, "label": "type"})
            elif t.o_is_iri:
                node(t.o, "entity")
                edges.append({"from": t.s, "to": t.o, "label": t.p})
            else:
                lit = f"{t.s}#{t.p}"
                node(lit, "literal", label=t.o)
                edges.append({"from": t.s, "to": lit, "label": t.p})
        return {"nodes": list(nodes.values()), "edges": edges}

    def to_dict(self) -> dict[str, Any]:
        return {
            "triples": [[t.s, t.p, t.o, t.o_is_iri] for t in self.triples],
            "turtle": self.to_turtle(),
            "view": self.to_view(),
            "count": len(self.triples),
        }


def build_subgraph(
    rows: list[dict],
    *,
    primary_class: str,
    fk_neighbors: list[dict] | None = None,
    inferred: list[dict] | None = None,
) -> Subgraph:
    """Materialize the result subgraph.

    ``fk_neighbors`` items: ``{subject_key, from_col, ref_table, ref_key, row}``.
    ``inferred`` items: the engine's derived-fact dicts (``fact`` = ``[pred, *args]``).
    """
    triples: list[Triple] = []

    def subj(cls: str, key: str) -> str:
        return f"{cls}/{key}"

    for i, row in enumerate(rows):
        key = str(row.get("id", i))
        s = subj(primary_class, key)
        triples.append(Triple(s, "rdf:type", primary_class, o_is_iri=True))
        for col, val in row.items():
            if val is None:
                continue
            triples.append(Triple(s, col, str(val)))

    for nb in fk_neighbors or []:
        s = subj(primary_class, str(nb["subject_key"]))
        ref = subj(nb["ref_table"], str(nb["ref_key"]))
        triples.append(Triple(s, nb["from_col"], ref, o_is_iri=True))
        triples.append(Triple(ref, "rdf:type", nb["ref_table"], o_is_iri=True))
        for col, val in (nb.get("row") or {}).items():
            if val is None:
                continue
            triples.append(Triple(ref, col, str(val)))

    for inf in inferred or []:
        fact = inf.get("fact") or []
        if len(fact) >= 2:
            pred, *args = fact
            s = subj(primary_class, str(args[0]))
            if len(args) == 1:                       # unary: subject rdf:type derived-class
                triples.append(Triple(s, "rdf:type", str(pred), o_is_iri=True))
            else:                                    # binary+: subject pred object
                triples.append(Triple(s, str(pred), str(args[1])))

    # de-dup, preserve order
    seen: set = set()
    uniq: list[Triple] = []
    for t in triples:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return Subgraph(triples=uniq)


# ── minimal SPARQL (SELECT + basic graph patterns) ───────────────────────────
_SELECT = re.compile(r"\bselect\b(.*?)\bwhere\b\s*\{(.*)\}", re.I | re.S)


def _is_var(tok: str) -> bool:
    return tok.startswith("?")


def _tokenize_pattern(line: str) -> list[str]:
    return re.findall(r'"[^"]*"|<[^>]*>|\S+', line.strip())


def _norm(tok: str) -> tuple[str, bool]:
    """Return (value, is_literal) — strips quotes / angle brackets."""
    if tok.startswith('"') and tok.endswith('"'):
        return tok[1:-1], True
    if tok.startswith("<") and tok.endswith(">"):
        return tok[1:-1], False
    return tok, False


def sparql(graph: Subgraph, query: str) -> dict[str, Any]:
    """Run a minimal SPARQL ``SELECT`` over the subgraph.

    Supports ``SELECT ?a ?b`` / ``SELECT *`` with a conjunctive WHERE block of
    ``s p o .`` triple patterns. ``a`` is shorthand for ``rdf:type``. Constants
    may be barewords, ``<iri>``, or ``"literal"``. Returns
    ``{"vars": [...], "rows": [{var: value}, ...]}``.
    """
    m = _SELECT.search(query or "")
    if not m:
        raise ValueError("only SELECT ... WHERE { ... } is supported")
    proj_raw = m.group(1).strip()
    body = m.group(2).strip()

    patterns: list[tuple[str, str, str]] = []
    for chunk in filter(None, (c.strip() for c in re.split(r"\.\s*(?=\?|<|\w|$)", body))):
        toks = _tokenize_pattern(chunk)
        if len(toks) < 3:
            continue
        patterns.append((toks[0], toks[1], " ".join(toks[2:]) if len(toks) > 3 else toks[2]))
    if not patterns:
        raise ValueError("no triple patterns found in WHERE block")

    def match(pat: tuple[str, str, str], t: Triple, b: dict) -> dict | None:
        nb = dict(b)
        for tok, val in ((pat[0], t.s), (pat[1], "rdf:type" if t.p in ("rdf:type", "a") else t.p), (pat[2], t.o)):
            if _is_var(tok):
                if tok in nb and nb[tok] != val:
                    return None
                nb[tok] = val
            else:
                want = "rdf:type" if tok == "a" else _norm(tok)[0]
                if want != val:
                    return None
        return nb

    solutions: list[dict] = [{}]
    for pat in patterns:
        nxt: list[dict] = []
        for b in solutions:
            for t in graph.triples:
                nb = match(pat, t, b)
                if nb is not None:
                    nxt.append(nb)
        solutions = nxt
        if not solutions:
            break

    if proj_raw in ("", "*"):
        vars_ = sorted({k for b in solutions for k in b})
    else:
        vars_ = [v for v in proj_raw.split() if _is_var(v)]

    seen: set = set()
    out_rows: list[dict] = []
    for b in solutions:
        row = {v: b.get(v, "") for v in vars_}
        key = tuple(row.items())
        if key not in seen:
            seen.add(key)
            out_rows.append(row)
    return {"vars": vars_, "rows": out_rows}
