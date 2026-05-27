"""L1.1 — LogCorpus iterator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from log_corpus import LogCorpus, LOG_EXTENSIONS  # noqa: E402


def _write_jsonl(path: Path, n: int = 5) -> None:
    with path.open("w") as f:
        for i in range(n):
            f.write(json.dumps({
                "ts": f"2026-05-07T09:00:{i:02d}Z",
                "severity": "INFO",
                "service": "TEST",
                "message": f"msg {i}",
            }) + "\n")


def test_resolves_single_file(tmp_path):
    f = tmp_path / "one.jsonl"
    _write_jsonl(f, 3)
    corpus = LogCorpus(str(f))
    assert corpus.resolve_files() == [str(f)]
    assert len(corpus.list()) == 3


def test_resolves_directory_recursively(tmp_path):
    (tmp_path / "service-a").mkdir()
    (tmp_path / "service-b").mkdir()
    _write_jsonl(tmp_path / "service-a" / "a.jsonl", 2)
    _write_jsonl(tmp_path / "service-b" / "b.jsonl", 3)
    _write_jsonl(tmp_path / "top.jsonl", 1)
    files = LogCorpus(str(tmp_path)).resolve_files()
    assert len(files) == 3
    assert all(f.endswith(".jsonl") for f in files)


def test_directory_walk_skips_unknown_extensions(tmp_path):
    _write_jsonl(tmp_path / "ok.jsonl", 1)
    (tmp_path / "ignore.tmp").write_text("garbage")
    (tmp_path / "ignore.png").write_bytes(b"PNG\x00")
    files = LogCorpus(str(tmp_path)).resolve_files()
    assert files == [str(tmp_path / "ok.jsonl")]


def test_glob_pattern(tmp_path):
    _write_jsonl(tmp_path / "alpha.jsonl", 2)
    _write_jsonl(tmp_path / "beta.jsonl", 2)
    _write_jsonl(tmp_path / "gamma.log", 2)  # different extension
    files = LogCorpus(str(tmp_path / "*.jsonl")).resolve_files()
    assert len(files) == 2
    assert all(f.endswith(".jsonl") for f in files)


def test_stats_track_files_and_records(tmp_path):
    _write_jsonl(tmp_path / "a.jsonl", 3)
    _write_jsonl(tmp_path / "b.jsonl", 4)
    corpus = LogCorpus(str(tmp_path))
    records = corpus.list()
    assert len(records) == 7
    assert corpus.stats.files_seen == 2
    assert corpus.stats.files_parsed == 2
    assert corpus.stats.records_yielded == 7
    assert corpus.stats.parse_errors == 0


def test_iteration_order_is_deterministic(tmp_path):
    """Two corpora over the same folder must yield the same record
    order — stable template ids depend on this."""
    _write_jsonl(tmp_path / "z.jsonl", 2)
    _write_jsonl(tmp_path / "a.jsonl", 2)
    _write_jsonl(tmp_path / "m.jsonl", 2)
    one = [r.message for r in LogCorpus(str(tmp_path)).iter()]
    two = [r.message for r in LogCorpus(str(tmp_path)).iter()]
    assert one == two
    # First file alphabetically is a.jsonl, so its records come first.
    assert one[0].startswith("msg")


def test_bundled_sample_corpus_loads():
    """The shipped sample under examples/log-rca/sample/ must parse
    cleanly. Fixture for downstream L1 tests."""
    sample_dir = ROOT / "examples" / "log-rca" / "sample"
    if not sample_dir.is_dir():
        pytest.skip("sample corpus not present")
    corpus = LogCorpus(str(sample_dir))
    records = corpus.list()
    assert len(records) >= 200, f"expected >=200 sample records, got {len(records)}"
    assert corpus.stats.parse_errors == 0
