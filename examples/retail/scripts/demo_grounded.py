"""Grounded runner — toolkit RuntimeClient path.

For every question in the bank, calls `RuntimeClient.ask(flavor='retail', ...)`
using both Anthropic and OpenAI adapters. The RuntimeClient pipeline handles
  - flavor selection + scoped context
  - grounding enterprise DB rows as JSON-LD
  - SHACL input gate (rejects malformed rows)
  - payload assembly (5 components: system prompt, ontology flavor, grounded
    data, PROV-O context, question)
  - LLM call via the chosen adapter
  - SHACL output gate + PROV-O stamping
  - ObservationRecord storage back into the DB

Each call returns: answer, valid (SHACL pass), observation_iri, prov
(model + timestamp + confidence + derivation). Output is cached to
`output/demo/cache/grounded_{vendor}_{qid}.json`.

Falls back to a clearly-marked placeholder when API keys are not set, so the
report builder works in offline demo mode.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(SCRIPT_DIR))

from demo_questions import QUESTIONS  # noqa: E402

CACHE_DIR = ROOT / "output" / "demo" / "cache"
DB_PATH = ROOT / "db" / "demo.db"
OUT_PATH = ROOT / "output" / "demo"


def placeholder(vendor: str, qid: str, reason: str) -> dict:
    return {
        "status": "NO_API_KEY",
        "vendor": vendor,
        "model": "",
        "question_id": qid,
        "answer": (
            f"[{vendor.upper()} grounded call skipped: {reason}. "
            "Set the API key and re-run `scripts/demo_grounded.py` — the SHACL gate, "
            "JSON-LD grounding, and PROV-O stamping will still run; only the LLM "
            "response is missing.]"
        ),
        "valid": None,
        "observation_iri": None,
        "prov": None,
        "elapsed_ms": 0,
        "flavor": "retail",
        "ontology_classes_in_payload": [
            "Customer", "Product", "Order", "OrderLine",
            "Invoice", "Payment", "Shipment", "OrderEvent",
        ],
    }


def run_one(vendor: str, model: str, question: dict) -> dict:
    from client import RuntimeClient  # from runtime/
    t0 = time.time()
    client = RuntimeClient(
        db_path=str(DB_PATH),
        adapter=vendor,
        model=model,
        out_path=str(OUT_PATH),
    )
    try:
        result = client.ask(
            question=question["text"],
            flavor="retail",
            output_format="json",
        )
    except Exception as exc:
        return placeholder(vendor, question["id"], f"RuntimeClient failed: {exc}")

    elapsed = int((time.time() - t0) * 1000)
    # Normalise for the comparison report.
    return {
        "status": "OK",
        "vendor": vendor,
        "model": result.get("model") or model,
        "question_id": question["id"],
        "question": question["text"],
        "flavor": result.get("flavor", "retail"),
        "answer": result.get("answer"),
        "valid": result.get("valid"),
        "violations": result.get("violations", []),
        "observation_iri": result.get("observation_iri"),
        "prov": result.get("prov"),
        "elapsed_ms": result.get("elapsed_ms", elapsed),
        "payload_id": result.get("payload_id"),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true")
    p.add_argument("--anthropic-model", default="claude-sonnet-4-5")
    p.add_argument("--openai-model", default="gpt-4o")
    args = p.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    have_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    have_openai = bool(os.environ.get("OPENAI_API_KEY"))

    if args.live and not (have_anthropic and have_openai):
        print("ERROR: --live requested but ANTHROPIC_API_KEY or OPENAI_API_KEY missing",
              file=sys.stderr)
        return 2

    for q in QUESTIONS:
        for vendor, have, model in [
            ("anthropic", have_anthropic, args.anthropic_model),
            ("openai",    have_openai,    args.openai_model),
        ]:
            out_path = CACHE_DIR / f"grounded_{vendor}_{q['id']}.json"
            if have:
                result = run_one(vendor, model, q)
            else:
                result = placeholder(vendor, q["id"], "API key not set")
                result["question"] = q["text"]
            out_path.write_text(json.dumps(result, indent=2, default=str))
            print(f"  ✓ {out_path.relative_to(ROOT)}  [{result['status']}]")

    print(f"\n  Grounded outputs in: {CACHE_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
