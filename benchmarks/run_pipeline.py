#!/usr/bin/env python3
"""benchmarks/run_pipeline.py — produce the numbers shown on the landing.

Runs the headless pipeline end-to-end against the bundled
``db/demo.db`` SQLite database, captures wall-clock time and the
counts that come out (classes, properties, SHACL shapes), and prints
a single JSON line that the landing page CSS pulls in.

Why JSON: the landing card stats need to be both human-readable
and machine-readable.  CI can run this and fail if numbers drift
beyond a tolerance band.

Usage
-----
    python3 benchmarks/run_pipeline.py
    python3 benchmarks/run_pipeline.py --db db/demo.db --out /tmp/bench
    python3 benchmarks/run_pipeline.py --json     # only the json, no banner

The output JSON is also written to ``benchmarks/last-run.json`` so the
landing page reads from a real file, not invented numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE   = Path(__file__).resolve().parent
ROOT   = HERE.parent
OUTPUT = HERE / "last-run.json"


# ── Counters ──────────────────────────────────────────────────────────


def _all_ttl_text(dir_path: Path) -> str:
    """Concatenate every ``.ttl`` file under ``dir_path`` so the
    counters work regardless of which filename the toolkit picks."""
    if not dir_path.exists():
        return ""
    out = []
    for f in sorted(dir_path.rglob("*.ttl")):
        try:
            out.append(f.read_text(errors="ignore"))
        except OSError:
            pass
    return "\n".join(out)


def _count_owl_classes(text: str) -> int:
    # ``a owl:Class``, ``rdf:type owl:Class``, and the rdflib-emitted
    # ``    owl:Class ;`` form on its own line.
    return sum(
        1 for line in text.splitlines()
        if "owl:Class" in line and (
            "a owl:Class" in line
            or "rdf:type owl:Class" in line
            or line.strip().startswith("owl:Class")
        )
    )


def _count_owl_properties(text: str) -> int:
    return sum(
        1 for line in text.splitlines()
        if ("owl:ObjectProperty" in line) or ("owl:DatatypeProperty" in line)
    )


def _count_shacl_shapes(text: str) -> int:
    return text.count("sh:NodeShape") + text.count("sh:PropertyShape")


def _bytes_human(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ── Run ───────────────────────────────────────────────────────────────


def run(db_path: Path, out_dir: Path, json_only: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    cmd = [
        sys.executable, str(ROOT / "toolkit.py"),
        "--db", str(db_path),
        "--out", str(out_dir),
    ]
    proc = subprocess.run(
        cmd, cwd=str(ROOT),
        capture_output=True, text=True, check=False, timeout=600,
    )
    elapsed = time.perf_counter() - t0

    owl_text   = _all_ttl_text(out_dir / "ontology")
    shacl_text = _all_ttl_text(out_dir / "shapes")

    result = {
        "ok":              proc.returncode == 0,
        "db":              str(db_path.relative_to(ROOT)),
        "db_bytes":        db_path.stat().st_size,
        "db_size_human":   _bytes_human(db_path.stat().st_size),
        "elapsed_seconds": round(elapsed, 2),
        "elapsed_human":   f"{elapsed:.1f} s",
        "owl_classes":     _count_owl_classes(owl_text),
        "owl_properties":  _count_owl_properties(owl_text),
        "shacl_shapes":    _count_shacl_shapes(shacl_text),
        "owl_bytes":       len(owl_text),
        "shacl_bytes":     len(shacl_text),
        "returncode":      proc.returncode,
    }
    if not result["ok"]:
        result["stderr_tail"] = (proc.stderr or "")[-2000:]

    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")

    if not json_only:
        print()
        print("  Ontomesh — benchmark run")
        print("  " + "─" * 38)
        print(f"  DB:           {result['db']} ({result['db_size_human']})")
        print(f"  Wall-clock:   {result['elapsed_human']}")
        print(f"  OWL classes:  {result['owl_classes']}")
        print(f"  Properties:   {result['owl_properties']}")
        print(f"  SHACL shapes: {result['shacl_shapes']}")
        print(f"  Status:       {'ok' if result['ok'] else 'failed'}")
        print(f"  Written to:   {OUTPUT.relative_to(ROOT)}")
        print()
    else:
        print(json.dumps(result))

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Ontomesh benchmark runner.")
    ap.add_argument("--db",   default=str(ROOT / "db" / "demo.db"))
    ap.add_argument("--out",  default=str(ROOT / "benchmarks" / "out"))
    ap.add_argument("--json", action="store_true",
                    help="Print only the JSON result (no banner).")
    args = ap.parse_args()
    result = run(Path(args.db), Path(args.out), json_only=args.json)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
