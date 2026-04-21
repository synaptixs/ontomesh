"""
entity_discoverer.py — Phase 3 · Sprint S15–S20
────────────────────────────────────────────────
Log Entity Discovery via NLP co-occurrence analysis.

Runs a statistical NLP pipeline over log corpora to surface candidate
entities and relationships NOT yet captured in the ontology. Produces a
scored candidate list for expert review — it never auto-adds to the ontology.
Results feed back into the onboarding wizard as entity suggestions.

Pipeline:
  1. Log loading — reads file(s) via log_connector format parsers
  2. Text extraction — strips timestamps/levels, keeps message body
  3. NLP (spaCy) — NER + noun-chunk extraction per log line
  4. Co-occurrence counting — sliding window over token pairs in each sentence
  5. Existing entity filtering — removes terms already in ontology_metadata
  6. Candidate scoring — TF-IDF style score weighted by co-occurrence frequency
  7. Output — scored CSV + JSON summary

Requires: pip install spacy && python -m spacy download en_core_web_sm

CLI:
  python3 toolkit.py --phase discover --log-path /var/log/app.log [--db db/enterprise.db]
"""

from __future__ import annotations

import os
import re
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Log line cleaner ───────────────────────────────────────────────────────

_TS_PATTERNS = [
    re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?\s*'),
    re.compile(r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+'),
    re.compile(r'^\d{10,13}\s+'),
]
_LEVEL_RE = re.compile(r'\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL|TRACE)\b\s*:?\s*', re.I)
_IP_RE    = re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}\b')
_HEX_RE   = re.compile(r'\b[0-9a-fA-F]{8,}\b')
_UUID_RE  = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
_NUM_RE   = re.compile(r'\b\d+(\.\d+)?\b')


def _clean_log_line(line: str) -> str:
    for pat in _TS_PATTERNS:
        line = pat.sub("", line, count=1)
    line = _LEVEL_RE.sub("", line)
    line = _UUID_RE.sub("UUID", line)
    line = _IP_RE.sub("IPADDR", line)
    line = _HEX_RE.sub("HEXVAL", line)
    line = _NUM_RE.sub("NUM", line)
    return line.strip()


def _load_log_lines(log_path: str, max_lines: int = 100_000) -> list[str]:
    lines: list[str] = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for i, raw in enumerate(f):
                if i >= max_lines:
                    break
                cleaned = _clean_log_line(raw.strip())
                if len(cleaned) > 10:
                    lines.append(cleaned)
    except OSError as e:
        print(f"  ⚠  Cannot read {log_path}: {e}")
    return lines


def _load_existing_entities(db_path: str) -> set[str]:
    """Load entity names already known to the ontology from ontology_metadata."""
    known: set[str] = set()
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT class_name, label FROM ontology_metadata"
        ).fetchall()
        conn.close()
        for class_name, label in rows:
            if class_name:
                known.add(class_name.lower())
                known.update(class_name.lower().split("_"))
            if label:
                known.update(label.lower().split())
    except Exception:
        pass
    return known


# ── NLP pipeline (with spaCy) ──────────────────────────────────────────────

def _run_spacy_pipeline(lines: list[str]) -> tuple[Counter, Counter, list[tuple[str, str]]]:
    """
    Returns:
      entity_counts   — Counter of entity surface forms (NER)
      noun_counts     — Counter of noun chunks
      relation_pairs  — list of (term_a, term_b) co-occurring in same sentence
    """
    try:
        import spacy
    except ImportError:
        print("  ⚠  spaCy not installed. Run: pip install spacy && python -m spacy download en_core_web_sm")
        return Counter(), Counter(), []

    try:
        nlp = spacy.load("en_core_web_sm", disable=["parser"])
        nlp.add_pipe("sentencizer")
    except OSError:
        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("  ⚠  spaCy model 'en_core_web_sm' not found. Run: python -m spacy download en_core_web_sm")
            return Counter(), Counter(), []

    entity_counts: Counter = Counter()
    noun_counts:   Counter = Counter()
    relation_pairs: list[tuple[str, str]] = []

    IGNORED_ENTS = {"CARDINAL", "ORDINAL", "DATE", "TIME", "PERCENT", "MONEY", "QUANTITY"}
    STOP_CHUNKS  = {"the", "a", "an", "this", "that", "it", "they", "we", "you", "i",
                    "uuid", "ipaddr", "hexval", "num", "error", "warning", "info"}

    batch_size = 500
    for i in range(0, len(lines), batch_size):
        batch = lines[i:i + batch_size]
        for doc in nlp.pipe(batch, batch_size=50):
            # NER
            ents_in_doc: list[str] = []
            for ent in doc.ents:
                if ent.label_ not in IGNORED_ENTS:
                    text = ent.text.lower().strip()
                    if len(text) > 2 and text not in STOP_CHUNKS:
                        entity_counts[text] += 1
                        ents_in_doc.append(text)

            # Noun chunks
            chunks_in_doc: list[str] = []
            for chunk in doc.noun_chunks:
                text = chunk.root.lemma_.lower().strip()
                if len(text) > 3 and text not in STOP_CHUNKS:
                    noun_counts[text] += 1
                    chunks_in_doc.append(text)

            # Co-occurrence within same doc (sentence-level proxy)
            all_terms = list(dict.fromkeys(ents_in_doc + chunks_in_doc))
            for j in range(len(all_terms)):
                for k in range(j + 1, min(j + 5, len(all_terms))):
                    a, b = sorted([all_terms[j], all_terms[k]])
                    if a != b:
                        relation_pairs.append((a, b))

    return entity_counts, noun_counts, relation_pairs


def _run_cooccurrence_fallback(lines: list[str]) -> tuple[Counter, Counter, list[tuple[str, str]]]:
    """
    Fallback tokeniser when spaCy is unavailable.
    Simple noun-phrase heuristic using capitalised tokens and common suffixes.
    """
    entity_counts: Counter = Counter()
    noun_counts:   Counter = Counter()
    relation_pairs: list[tuple[str, str]] = []

    ENTITY_SUFFIXES = ("Manager", "Service", "Handler", "Controller", "Server",
                       "Client", "Agent", "Node", "Worker", "Process", "Task",
                       "Queue", "Event", "Error", "Status", "Connection")

    for line in lines:
        tokens = re.findall(r'\b[A-Z][a-zA-Z0-9]+\b', line)
        candidates = [t for t in tokens if any(t.endswith(s) for s in ENTITY_SUFFIXES)]
        for tok in candidates:
            entity_counts[tok.lower()] += 1
        for j in range(len(candidates)):
            for k in range(j + 1, min(j + 4, len(candidates))):
                a, b = sorted([candidates[j].lower(), candidates[k].lower()])
                if a != b:
                    relation_pairs.append((a, b))
    noun_counts = Counter()
    return entity_counts, noun_counts, relation_pairs


def _score_candidates(entity_counts: Counter,
                       noun_counts: Counter,
                       relation_pairs: list[tuple[str, str]],
                       known_entities: set[str],
                       min_freq: int = 3) -> list[dict]:
    """
    Score and rank entity candidates. Filter out known entities.
    Returns sorted list of candidate dicts.
    """
    # Merge entity and noun counts
    combined: Counter = Counter()
    for term, cnt in entity_counts.items():
        combined[term] += cnt * 2
    for term, cnt in noun_counts.items():
        combined[term] += cnt

    # Co-occurrence frequency
    cooc_counts: Counter = Counter(relation_pairs)

    total_docs = max(sum(combined.values()), 1)
    vocab_size  = len(combined)

    candidates: list[dict] = []
    for term, freq in combined.items():
        if freq < min_freq:
            continue
        if term in known_entities:
            continue
        if len(term) < 4:
            continue
        # TF-IDF style score
        tf   = freq / total_docs
        idf  = math.log(total_docs / (freq + 1)) + 1
        score = round(tf * idf * 100, 4)

        # Find top co-occurring partners
        partners = [
            (a if b == term else b, cnt)
            for (a, b), cnt in cooc_counts.most_common(200)
            if (a == term or b == term)
        ][:5]

        candidates.append({
            "candidate_entity":   term,
            "frequency":          freq,
            "score":              score,
            "co_occurring_with":  ", ".join(f"{p}({c})" for p, c in partners),
            "already_in_ontology": "No",
            "suggested_class_name": "".join(w.capitalize() for w in term.split()),
            "review_status":       "Pending",
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


# ── Main entry point ────────────────────────────────────────────────────────

def run_entity_discovery(log_path: str, db_path: str,
                          out_path: str,
                          min_freq: int = 3,
                          max_lines: int = 100_000) -> dict:
    """
    Run the full entity discovery pipeline over a log file.
    Returns a summary dict.
    """
    rpt_dir = os.path.join(out_path, "reports")
    os.makedirs(rpt_dir, exist_ok=True)

    print(f"  Log file  : {log_path}")
    print(f"  Min freq  : {min_freq}")
    print(f"  Max lines : {max_lines:,}")

    lines = _load_log_lines(log_path, max_lines)
    print(f"  Lines read: {len(lines):,}")
    if not lines:
        print("  ⚠  No log lines extracted.")
        return {}

    known = _load_existing_entities(db_path)
    print(f"  Known entities from ontology: {len(known)}")

    print("  Running NLP pipeline...")
    try:
        import spacy
        entity_counts, noun_counts, relation_pairs = _run_spacy_pipeline(lines)
        backend = "spaCy"
    except ImportError:
        entity_counts, noun_counts, relation_pairs = _run_cooccurrence_fallback(lines)
        backend = "fallback-regex"

    print(f"  NLP backend: {backend}")
    print(f"  Unique entities (NER): {len(entity_counts)}")
    print(f"  Unique noun chunks:    {len(noun_counts)}")
    print(f"  Co-occurrence pairs:   {len(relation_pairs):,}")

    candidates = _score_candidates(entity_counts, noun_counts, relation_pairs, known, min_freq)
    print(f"  Candidate entities (novel, freq≥{min_freq}): {len(candidates)}")

    if not candidates:
        print("  ✓ No novel entity candidates found.")
        return {"candidates": 0}

    # Write CSV
    csv_path = os.path.join(rpt_dir, "entity_discovery_candidates.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(candidates[0].keys()))
        w.writeheader()
        w.writerows(candidates[:200])
    print(f"  ✓ Candidate CSV → {csv_path} ({min(len(candidates),200)} top candidates)")

    # Write JSON summary
    summary = {
        "generated":            NOW,
        "log_path":             log_path,
        "lines_processed":      len(lines),
        "nlp_backend":          backend,
        "known_entity_count":   len(known),
        "candidates_found":     len(candidates),
        "top_candidates":       candidates[:20],
    }
    json_path = os.path.join(rpt_dir, "entity_discovery_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"  ✓ Discovery summary → {json_path}")

    if candidates:
        print(f"\n  Top 10 novel entity candidates:")
        print(f"  {'Entity':<35} {'Freq':>6}  {'Score':>8}  Co-occurring with")
        print(f"  {'-'*35} {'-'*6}  {'-'*8}  {'-'*30}")
        for c in candidates[:10]:
            print(f"  {c['candidate_entity']:<35} {c['frequency']:>6}  {c['score']:>8.4f}  {c['co_occurring_with'][:40]}")

    return summary
