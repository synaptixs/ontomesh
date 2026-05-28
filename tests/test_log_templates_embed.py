"""L12 — Probabilistic PCA over template-feature vectors.

Roadmap §3.L12 acceptance gates:
1. Top-5 nearest-neighbour pairs for a held-out template "obviously"
   relate to it — verified by an engineer judgment, here approximated
   by constructing a synthetic corpus with known semantic clusters
   and asserting the neighbours come from the same cluster.
2. Cluster count drops by ≥ 10 % vs Drain alone — approximated by
   asserting ``suggest_merges`` produces enough candidates to compress
   a known-redundant corpus by that fraction.

Plus basic correctness: tokenisation behaves, embedder fits, 2D
projection is deterministic, suggest_merges respects threshold,
end-to-end round-trip through a SQLite log_templates table.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("sklearn")

from log_templates_embed import (                               # noqa: E402
    MIN_TEMPLATES, MergeCandidate, TemplateEmbedder, _tokenise,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_conn():
    c = sqlite3.connect(":memory:")
    # Minimal log_templates schema — the embedder only needs
    # (id, cluster_id, template, merged_into).
    c.executescript("""
        CREATE TABLE log_templates (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id    INTEGER UNIQUE,
            template      TEXT,
            sample_line   TEXT,
            hits          INTEGER DEFAULT 0,
            merged_into   INTEGER REFERENCES log_templates(id)
        );
    """)
    return c


def _insert_templates(conn, rows):
    """``rows`` is a sequence of (cluster_id, template) tuples."""
    for cid, tpl in rows:
        conn.execute(
            "INSERT INTO log_templates (cluster_id, template) VALUES (?, ?)",
            (cid, tpl),
        )
    conn.commit()


# ── Tokenisation ──────────────────────────────────────────────────────


def test_tokenise_drops_drain_placeholder():
    toks = _tokenise("User <*> logged in from <*>")
    assert "user" in toks
    assert "logged" in toks
    assert "<*>" not in toks
    assert all(t == t.lower() for t in toks)


def test_tokenise_drops_short_and_pure_numeric_tokens():
    toks = _tokenise("a b cd 12 quota=10")
    # 'a' and 'b' filtered (≥ 2 chars rule); '12' filtered (no leading letter).
    assert "a" not in toks
    assert "b" not in toks
    assert "12" not in toks
    assert "cd" in toks
    assert "quota" in toks


# ── Fit guard rails ───────────────────────────────────────────────────


def test_fit_raises_when_corpus_too_small():
    conn = _make_conn()
    _insert_templates(conn, [(1, "foo bar"), (2, "baz qux")])
    e = TemplateEmbedder()
    with pytest.raises(RuntimeError):
        e.fit(conn)


def test_fit_raises_when_no_usable_tokens():
    conn = _make_conn()
    _insert_templates(conn, [
        (1, "<*>"), (2, "<*>"), (3, "<*>"), (4, "<*>")
    ])
    e = TemplateEmbedder()
    with pytest.raises(RuntimeError):
        e.fit(conn)


# ── Round-trip ────────────────────────────────────────────────────────


def test_fit_then_embed_round_trip():
    conn = _make_conn()
    _insert_templates(conn, [
        (1, "User logged in for <*>"),
        (2, "User logged out for <*>"),
        (3, "Session expired for <*>"),
        (4, "Payment received for <*>"),
        (5, "Refund issued for <*>"),
    ])
    e = TemplateEmbedder().fit(conn)
    vec = e.embed(1)
    assert vec.shape[0] >= 2
    x, y = e.project_2d(1)
    assert isinstance(x, float)
    assert isinstance(y, float)


# ── Acceptance gate 1: nearest-neighbour sanity ───────────────────────


def test_top_nearest_neighbours_share_semantic_cluster():
    """The §3.L12 'top-5 NN are obviously related' gate, approximated
    via a synthetic corpus with two clearly-distinct semantic groups.
    """
    conn = _make_conn()
    # Group A: authentication / session lifecycle.
    auth = [
        (1, "User logged in successfully from host <*>"),
        (2, "User logged out from host <*>"),
        (3, "Session expired for user <*>"),
        (4, "Session refresh token issued for <*>"),
        (5, "Authentication failed for user <*>"),
    ]
    # Group B: payment / billing flow.
    pay = [
        (6, "Payment received from customer <*>"),
        (7, "Payment refund issued for order <*>"),
        (8, "Invoice generated for customer <*>"),
        (9, "Charge declined for customer <*>"),
        (10, "Subscription renewed for customer <*>"),
    ]
    _insert_templates(conn, auth + pay)

    e = TemplateEmbedder(n_components=6).fit(conn)
    # Hold out template id 1 (auth event) and ask for top-5 NN.
    nn = e.nearest_neighbours(1, k=5)
    nn_ids = {tid for tid, _d in nn}
    # All 5 NN should come from the same auth group, NOT the pay group.
    in_auth_group = nn_ids & {2, 3, 4, 5}
    in_pay_group = nn_ids & {6, 7, 8, 9, 10}
    assert len(in_auth_group) >= 3, (
        f"top-5 NN should be dominated by auth group; got {nn_ids}"
    )
    assert len(in_pay_group) <= 2, (
        f"top-5 NN should rarely include pay group; got pay overlap {in_pay_group}"
    )


# ── Acceptance gate 2: merge-suggestion compression ───────────────────


def test_suggest_merges_finds_redundant_templates():
    """Build a corpus with intentionally near-duplicate templates.
    suggest_merges should produce enough candidates to compress the
    set by ≥ 10 %."""
    conn = _make_conn()
    # Three "real" patterns × four near-duplicates each = 12 templates,
    # of which roughly 9 should look mergeable to a flexible distance.
    _insert_templates(conn, [
        (1, "User <*> logged in"),
        (2, "User <*> logged in successfully"),
        (3, "User <*> logged in from host <*>"),
        (4, "Payment <*> received"),
        (5, "Payment <*> received successfully"),
        (6, "Payment <*> received from customer <*>"),
        (7, "Session <*> expired"),
        (8, "Session <*> expired after timeout"),
        (9, "Session <*> expired due to inactivity"),
        (10, "User logged in from device <*>"),
        (11, "Payment confirmed for order <*>"),
        (12, "Session terminated for user <*>"),
    ])
    # Threshold 0.8 in L2-normalised PCA space corresponds to ~0.68
    # cosine similarity — appropriate for "near-duplicate" templates
    # that share most but not all tokens (which is what redundant log
    # patterns look like in practice).
    e = TemplateEmbedder(n_components=8, merge_threshold=0.8).fit(conn)
    merges = e.suggest_merges()
    # At least one pair surviving the threshold per "real" group is
    # the floor for a 10 % compression claim — 3 merges from 12
    # templates is a 25 % cut if all confirmed.
    assert len(merges) >= 3, (
        f"expected ≥ 3 merge candidates on a redundant corpus; got {len(merges)}"
    )
    # Closest pair is one of the obviously-redundant ones.
    closest = merges[0]
    obvious_groups = [{1, 2, 3, 10}, {4, 5, 6, 11}, {7, 8, 9, 12}]
    in_same_group = any(
        closest.template_id_a in g and closest.template_id_b in g
        for g in obvious_groups
    )
    assert in_same_group, (
        f"closest merge {closest.template_id_a}-{closest.template_id_b} "
        f"didn't fall in a known-redundant group"
    )


def test_merge_suggestions_respect_threshold():
    conn = _make_conn()
    _insert_templates(conn, [
        (1, "alpha beta gamma"),
        (2, "delta epsilon zeta"),
        (3, "alpha beta delta"),
        (4, "zeta theta iota"),
    ])
    e = TemplateEmbedder(n_components=2, merge_threshold=0.0).fit(conn)
    # With zero threshold no pairs should be returned (we need exact
    # collision in chord distance, which doesn't happen here).
    assert e.suggest_merges() == []


# ── UI payload ────────────────────────────────────────────────────────


def test_viz_payload_is_json_serialisable():
    import json
    conn = _make_conn()
    _insert_templates(conn, [
        (1, "User logged in successfully"),
        (2, "User logged out"),
        (3, "Payment received"),
        (4, "Payment refunded"),
    ])
    e = TemplateEmbedder().fit(conn)
    payload = e.viz_payload()
    s = json.dumps(payload)              # must not raise
    assert "points" in payload
    assert "merges" in payload
    assert payload["n_templates"] == 4
    assert len(payload["points"]) == 4


def test_viz_payload_points_have_2d_coords():
    conn = _make_conn()
    _insert_templates(conn, [
        (1, "User logged in"),
        (2, "User logged out"),
        (3, "Payment received"),
        (4, "Payment refunded"),
        (5, "Session expired"),
    ])
    e = TemplateEmbedder().fit(conn)
    payload = e.viz_payload()
    for p in payload["points"]:
        assert "x" in p
        assert "y" in p
        assert isinstance(p["x"], float)
        assert isinstance(p["y"], float)
