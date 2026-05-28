"""
log_corpus.py — Phase L1.1
──────────────────────────
Folder-pointer iterator that the mining pipeline (Drain template
clustering, PMI graph, HMM, Granger) reads from.

Reuses :mod:`log_connector`'s parsers so JSON-Lines, syslog (RFC5424),
CEF, and OTLP all flow through the same code path. Pure read — no
database writes. The miner persists templates separately.

Usage::

    from log_corpus import LogCorpus
    for rec in LogCorpus("/var/log/myservice/").iter():
        process(rec)   # rec is a LogRecord with timestamp + message + service

`path` may be:
    - a single file        → that file
    - a glob               → every match
    - a directory          → every supported log file under it
                             (.jsonl / .json / .log / .syslog / .cef / .otlp)
                             walked recursively

When a directory is supplied the iterator yields records sorted by file
name so successive ``--phase mine`` runs see the same record order
(stable template ids).
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
import sys
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from log_connector import LogRecord, _iter_records  # noqa: E402


# Default file extensions treated as "log content" when walking a folder.
# Conservative on purpose — picking up everything under `/var/log/` would
# include rotated/compressed files we don't decompress here.
LOG_EXTENSIONS = (".jsonl", ".json", ".log", ".syslog", ".cef", ".otlp", ".txt")


@dataclass
class CorpusStats:
    files_seen: int = 0
    files_parsed: int = 0
    records_yielded: int = 0
    parse_errors: int = 0

    def as_dict(self) -> dict:
        return {
            "files_seen":      self.files_seen,
            "files_parsed":    self.files_parsed,
            "records_yielded": self.records_yielded,
            "parse_errors":    self.parse_errors,
        }


class LogCorpus:
    """Stateful iterator over a folder/glob of log files."""

    def __init__(self, path: str, *, fmt: str = "auto",
                 custom_regex: Optional[str] = None,
                 extensions: Iterable[str] = LOG_EXTENSIONS):
        self.path = path
        self.fmt = fmt
        self.custom_regex = custom_regex
        self.extensions = tuple(ext.lower() for ext in extensions)
        self.stats = CorpusStats()

    # ── path resolution ────────────────────────────────────────────────

    def resolve_files(self) -> List[str]:
        """Return the list of files this corpus will read, sorted for
        determinism."""
        files: List[str] = []
        if os.path.isdir(self.path):
            for root, _dirs, names in os.walk(self.path):
                for name in names:
                    if name.lower().endswith(self.extensions):
                        files.append(os.path.join(root, name))
        elif any(ch in self.path for ch in "*?["):
            files = list(glob.glob(self.path))
        elif os.path.isfile(self.path):
            files = [self.path]
        return sorted(files)

    # ── iteration ──────────────────────────────────────────────────────

    def iter(self) -> Iterator[LogRecord]:
        """Yield every parseable record across every resolved file."""
        files = self.resolve_files()
        self.stats = CorpusStats(files_seen=len(files))
        for path in files:
            parsed_count = 0
            try:
                for rec in _iter_records(path, fmt=self.fmt,
                                         custom_regex=self.custom_regex):
                    parsed_count += 1
                    self.stats.records_yielded += 1
                    yield rec
            except Exception:  # noqa: BLE001 — never let one file kill the run
                self.stats.parse_errors += 1
                continue
            if parsed_count:
                self.stats.files_parsed += 1

    # Conveniences for callers that want everything in memory.

    def list(self) -> List[LogRecord]:
        return list(self.iter())

    def __iter__(self) -> Iterator[LogRecord]:
        return self.iter()


__all__ = ["LogCorpus", "CorpusStats", "LOG_EXTENSIONS"]
