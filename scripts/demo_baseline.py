"""Baseline runner — raw SQL rows → plain LLM prompt. No ontology.

For each question in the bank, dump the relevant tables as JSON, paste into a
plain-prose system prompt, and call Anthropic + OpenAI. Save every answer to
`output/demo/cache/baseline_{vendor}_{qid}.json`.

If an API key is missing, the script writes a placeholder with
`"status": "NO_API_KEY"` so the report builder can still render the demo.
Run with `--live` to force live calls (fails loudly if keys missing).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from demo_questions import QUESTIONS  # noqa: E402

CACHE_DIR = ROOT / "output" / "demo" / "cache"
DB_PATH = ROOT / "db" / "demo.db"

SYSTEM_PROMPT = (
    "You are a helpful retail analyst. Answer the user's question using ONLY "
    "the JSON rows provided. Keep your answer short and precise."
)


def dump_tables(conn: sqlite3.Connection, tables: list[str]) -> str:
    out = {}
    for t in tables:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
        out[t] = rows
    return json.dumps(out, indent=2, default=str)


def call_anthropic(model: str, system: str, user: str) -> dict:
    import anthropic
    t0 = time.time()
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=600,
        temperature=0.2,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    elapsed = int((time.time() - t0) * 1000)
    text = "".join(b.text for b in resp.content if b.type == "text")
    return {
        "status": "OK",
        "vendor": "anthropic",
        "model": model,
        "answer": text,
        "elapsed_ms": elapsed,
        "usage": {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
    }


def call_openai(model: str, system: str, user: str) -> dict:
    import openai
    t0 = time.time()
    client = openai.OpenAI()
    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=600,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    elapsed = int((time.time() - t0) * 1000)
    return {
        "status": "OK",
        "vendor": "openai",
        "model": model,
        "answer": resp.choices[0].message.content,
        "elapsed_ms": elapsed,
        "usage": {
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
        },
    }


def placeholder(vendor: str, qid: str, reason: str) -> dict:
    return {
        "status": "NO_API_KEY",
        "vendor": vendor,
        "model": "",
        "answer": (
            f"[{vendor.upper()} call skipped: {reason}. "
            "Set the API key and re-run `scripts/demo_baseline.py` to populate this cell "
            "with a real response. The comparison report will read whatever is in the cache.]"
        ),
        "elapsed_ms": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="fail if API keys missing")
    p.add_argument("--anthropic-model", default="claude-sonnet-4-5")
    p.add_argument("--openai-model", default="gpt-4o")
    args = p.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    have_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    have_openai = bool(os.environ.get("OPENAI_API_KEY"))

    if args.live and not (have_anthropic and have_openai):
        print("ERROR: --live requested but ANTHROPIC_API_KEY or OPENAI_API_KEY missing",
              file=sys.stderr)
        return 2

    for q in QUESTIONS:
        rows_json = dump_tables(conn, q["tables_for_baseline"])
        user = f"Data:\n{rows_json}\n\nQuestion: {q['text']}"

        for vendor, have, model, fn in [
            ("anthropic", have_anthropic, args.anthropic_model, call_anthropic),
            ("openai",    have_openai,    args.openai_model,    call_openai),
        ]:
            out_path = CACHE_DIR / f"baseline_{vendor}_{q['id']}.json"
            if have:
                try:
                    result = fn(model, SYSTEM_PROMPT, user)
                except Exception as exc:
                    result = placeholder(vendor, q["id"], f"API call failed: {exc}")
            else:
                result = placeholder(vendor, q["id"], "API key not set")
            result["question_id"] = q["id"]
            result["question"] = q["text"]
            out_path.write_text(json.dumps(result, indent=2))
            print(f"  ✓ {out_path.relative_to(ROOT)}  [{result['status']}]")

    print(f"\n  Baseline outputs in: {CACHE_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
