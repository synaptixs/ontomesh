"""``ontoforge search`` — CLI surface for reasoning search (§11 #15).

Invoked by the ``ontomesh`` console shim when the first arg is ``search``; it
does not touch ``toolkit.py``'s flag surface.

    ontoforge search "which customers are platinum?" --flavor network-ops --db db/demo.db
    ontoforge search "…" --flavor clinical-research --provider openai --json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict


def run(argv: list[str]) -> int:
    """Parse args, run a search, print the result. Returns a shell exit code."""
    p = argparse.ArgumentParser(
        prog="ontoforge search",
        description="Ontology-grounded reasoning search over a connected database.",
    )
    p.add_argument("question", help="natural-language question")
    p.add_argument("--flavor", required=True, help="ontology flavor / scope")
    p.add_argument("--db", default=None, help="database path/connection (read-only)")
    p.add_argument("--provider", default="ollama", help="ollama | openai")
    p.add_argument("--max-tier", default="Internal", help="access ceiling (sensitivity tier)")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="emit the full ReasonedAnswer as JSON")
    args = p.parse_args(argv)

    from runtime.reasoning_search import search

    ans = search(
        args.question, flavor=args.flavor, db_path=args.db,
        providers=args.provider, max_tier=args.max_tier, k=args.k,
    )

    if args.as_json:
        print(json.dumps(asdict(ans), default=str, indent=2))
    else:
        print(ans.answer)
        print()
        if ans.executed_query:
            print(f"  query: {ans.executed_query}")
        if ans.citations:
            print("  sources:")
            for c in ans.citations:
                tag = " (inferred)" if c.inferred else ""
                print(f"    - {c.iri}{tag}  [{c.source_table}]")
        print(f"  confidence: {ans.confidence:.0%} · status: {ans.status} · provider: {ans.provider}")

    return 0 if ans.status in ("ok", "empty") else 1
