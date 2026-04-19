#!/usr/bin/env python3
"""
apply_url_config.py — Replace placeholder URLs with customer URLs.
──────────────────────────────────────────────────────────────────

Reads config/urls.yaml (or another file via --config) and rewrites every
occurrence of the toolkit's shipped placeholder URL prefixes with the
customer-supplied values.

It operates in three modes:

  --target source   Rewrite src/*.py and db/*.sql        (default)
  --target output   Rewrite everything under output/
  --target all      Both of the above

And two run modes:

  --dry-run         Print planned changes, don't touch disk (default)
  --apply           Write changes. Originals are saved as *.bak
                    unless --no-backup is given.

STANDARDS URIs (W3C, Dublin Core, TM Forum public docs) are NEVER
rewritten — see STANDARDS_ALLOWLIST below.

Usage
─────
    # Preview
    python scripts/apply_url_config.py --dry-run

    # Apply to source (db_introspector, tmf_mapper, seeds, etc.)
    python scripts/apply_url_config.py --apply --target source

    # Apply to everything (source + output/)
    python scripts/apply_url_config.py --apply --target all

    # Use a different config file
    python scripts/apply_url_config.py --apply --config config/acme.yaml

Exit codes: 0 on success, 1 on config or I/O error.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# ── Shipped placeholder values (the "before" side of every rewrite) ──
# These MUST match what currently exists in the codebase. Keep in sync
# with src/db_introspector.py and src/tmf_mapper.py.
DEFAULT_ONTOLOGY = {
    "base":       "https://ontology.example.com/enterprise/",
    "shapes":     "https://ontology.example.com/shapes/enterprise/",
    "vocab":      "https://ontology.example.com/vocab/enterprise/",
    "tmf":        "https://ontology.example.com/tmf/",
    "org_domain": "ontology.example.com",
}
DEFAULT_INSTANCE = {
    # NOTE: Order matters — longer/more-specific prefixes must come first
    # so that "oss.gtc.example.com" is matched before "gtc.example.com".
    "oss":   "https://oss.gtc.example.com/",
    "ml":    "https://ml.gtc.example.com/",
    "audit": "https://audit.gtc.example.com/",
    "base":  "https://gtc.example.com/",
}

# ── URIs we refuse to rewrite even if their prefix matched (belt &
#    suspenders). These are canonical vocabularies whose IRIs are
#    specified by external standards bodies. ───────────────────────────
STANDARDS_ALLOWLIST: Tuple[str, ...] = (
    "http://www.w3.org/",
    "https://www.w3.org/",
    "http://purl.org/dc/",
    "https://purl.org/dc/",
    "https://www.tmforum.org/",
    "http://www.tmforum.org/",
    "https://github.com/tmforum-apis",
)

# ── File-selection rules ────────────────────────────────────────────
SOURCE_GLOBS = ("src/*.py", "db/*.sql", "toolkit.py")
OUTPUT_GLOB  = "output/**/*"
# Text file extensions that are safe to rewrite. Anything else (e.g.
# .db, .png, .pyc) is skipped even if matched by the glob.
TEXT_EXTENSIONS = {
    ".py", ".sql", ".md", ".ttl", ".jsonld", ".json",
    ".csv", ".yaml", ".yml", ".txt", ".html",
}


# ── Data classes & loader ───────────────────────────────────────────

@dataclass(frozen=True)
class Substitution:
    old: str
    new: str
    label: str  # human-readable tag used in the report

    def matches(self, text: str) -> int:
        return text.count(self.old)


def _read_yaml(path: Path) -> dict:
    """
    Minimal YAML reader for the flat two-level structure used by
    config/urls.yaml. Avoids a PyYAML dependency.
    Supports: top-level keys, nested mappings one level deep, and
    '#'-line comments. Values may be quoted or unquoted scalars.
    """
    data: Dict[str, dict] = {}
    current: str | None = None
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):
            # top-level "key:" — start a new section
            if line.endswith(":"):
                current = line[:-1].strip()
                data[current] = {}
                continue
            raise ValueError(f"Unexpected top-level line: {raw!r}")
        if current is None:
            raise ValueError(f"Indented line with no section: {raw!r}")
        if ":" not in line:
            raise ValueError(f"Expected 'key: value' on indented line: {raw!r}")
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        data[current][key.strip()] = value
    return data


def load_substitutions(config_path: Path) -> List[Substitution]:
    cfg = _read_yaml(config_path)
    if "ontology" not in cfg or "instance" not in cfg:
        raise ValueError("config must define both 'ontology' and 'instance' sections")

    subs: List[Substitution] = []

    # Ontology — required keys
    for key in ("base", "shapes", "vocab", "tmf"):
        old = DEFAULT_ONTOLOGY[key]
        new = cfg["ontology"].get(key)
        if not new:
            raise ValueError(f"ontology.{key} is required in config")
        if not new.endswith("/"):
            raise ValueError(f"ontology.{key} must end with '/': {new!r}")
        if old != new:
            subs.append(Substitution(old, new, f"ontology.{key}"))

    # Instance — required keys. Longer prefixes first (see DEFAULT_INSTANCE).
    for key in ("oss", "ml", "audit", "base"):
        old = DEFAULT_INSTANCE[key]
        new = cfg["instance"].get(key)
        if not new:
            raise ValueError(f"instance.{key} is required in config")
        if not new.endswith("/"):
            raise ValueError(f"instance.{key} must end with '/': {new!r}")
        if old != new:
            subs.append(Substitution(old, new, f"instance.{key}"))

    # Bare org_domain (no scheme) — applied LAST so it can't eat URLs.
    old_dom = DEFAULT_ONTOLOGY["org_domain"]
    new_dom = cfg["ontology"].get("org_domain")
    if not new_dom:
        raise ValueError("ontology.org_domain is required in config")
    if old_dom != new_dom:
        subs.append(Substitution(old_dom, new_dom, "ontology.org_domain"))

    return subs


# ── File discovery ──────────────────────────────────────────────────

def discover_files(root: Path, target: str) -> List[Path]:
    files: List[Path] = []
    if target in ("source", "all"):
        for g in SOURCE_GLOBS:
            files.extend(root.glob(g))
    if target in ("output", "all"):
        for p in root.glob(OUTPUT_GLOB):
            if p.is_file():
                files.append(p)
    # Filter to text extensions only; de-duplicate; sort for stable output.
    uniq = sorted({p.resolve() for p in files if p.suffix.lower() in TEXT_EXTENSIONS})
    return uniq


# ── Rewriter ────────────────────────────────────────────────────────

def _guard_standards(text: str) -> List[Tuple[int, int]]:
    """
    Return (start, end) spans covering every standards-allowlisted URI
    so the substitution step can skip them. We match conservatively: a
    span begins at an allowlisted prefix and extends until the next
    whitespace or closing quote/paren/angle-bracket character.
    """
    spans: List[Tuple[int, int]] = []
    for prefix in STANDARDS_ALLOWLIST:
        start = 0
        while True:
            i = text.find(prefix, start)
            if i == -1:
                break
            # extend to first terminator
            j = i
            terminators = set(" \t\n\r\"'<>`)]},;")
            while j < len(text) and text[j] not in terminators:
                j += 1
            spans.append((i, j))
            start = j
    # merge overlapping spans
    spans.sort()
    merged: List[Tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _in_span(pos: int, spans: List[Tuple[int, int]]) -> bool:
    # simple linear scan — spans list is small in practice
    for s, e in spans:
        if s <= pos < e:
            return True
        if pos < s:
            return False
    return False


def rewrite_text(text: str, subs: Iterable[Substitution]) -> Tuple[str, Dict[str, int]]:
    """
    Apply substitutions one at a time, skipping any match that lies
    inside a standards-allowlisted span. Returns (new_text, counts).
    """
    counts: Dict[str, int] = {}
    for sub in subs:
        # Recompute guard spans per sub because the text mutates.
        guard = _guard_standards(text)
        out: List[str] = []
        i = 0
        n = 0
        while True:
            j = text.find(sub.old, i)
            if j == -1:
                out.append(text[i:])
                break
            if _in_span(j, guard):
                out.append(text[i:j + len(sub.old)])
                i = j + len(sub.old)
                continue
            out.append(text[i:j])
            out.append(sub.new)
            i = j + len(sub.old)
            n += 1
        text = "".join(out)
        if n:
            counts[sub.label] = n
    return text, counts


# ── Driver ──────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    root_default = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default=str(root_default / "config" / "urls.yaml"),
                    help="Path to urls.yaml (default: config/urls.yaml)")
    ap.add_argument("--root",   default=str(root_default),
                    help="Project root to scan (default: repo root)")
    ap.add_argument("--target", choices=("source", "output", "all"),
                    default="source", help="Which files to rewrite")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Report changes without writing (default)")
    mode.add_argument("--apply",   action="store_true",
                      help="Actually write changes")
    ap.add_argument("--no-backup", action="store_true",
                    help="Skip writing .bak backups when applying")
    args = ap.parse_args(argv)

    if args.apply:
        args.dry_run = False

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(f"[error] config not found: {cfg_path}", file=sys.stderr)
        return 1
    try:
        subs = load_substitutions(cfg_path)
    except Exception as e:
        print(f"[error] invalid config: {e}", file=sys.stderr)
        return 1

    if not subs:
        print("[ok] config matches the shipped placeholders — nothing to do.")
        return 0

    print("Planned substitutions:")
    for s in subs:
        print(f"  {s.label:22s}  {s.old}  →  {s.new}")
    print()

    files = discover_files(Path(args.root), args.target)
    print(f"Scanning {len(files)} file(s) under target={args.target}...\n")

    total_by_label: Dict[str, int] = {}
    total_files_changed = 0
    for path in files:
        try:
            original = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — skip silently
        new_text, counts = rewrite_text(original, subs)
        if not counts:
            continue
        total_files_changed += 1
        rel = path.relative_to(Path(args.root))
        summary = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
        action = "would update" if args.dry_run else "updating"
        print(f"  {action:14s} {rel}  ({summary})")
        for k, v in counts.items():
            total_by_label[k] = total_by_label.get(k, 0) + v
        if not args.dry_run:
            if not args.no_backup:
                path.with_suffix(path.suffix + ".bak").write_text(original)
            path.write_text(new_text)

    print()
    print(f"Totals: {total_files_changed} file(s), "
          f"{sum(total_by_label.values())} substitution(s).")
    for k, v in sorted(total_by_label.items()):
        print(f"  {k:22s} {v}")
    if args.dry_run:
        print("\n(dry-run — nothing written. Re-run with --apply to commit.)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
