"""L11 — PC algorithm causal structure learning.

Roadmap §3.L11 acceptance gate, on a synthetic 3-node corpus where
A causes both B and C (no direct B↔C link):

  - v1 Granger gives A→B, A→C, B↔C (spurious — B and C are
    pairwise-correlated through their shared cause A)
  - v2 PC gives A→B, A→C only — the B↔C edge dies once we condition
    on A in the skeleton CI step.

This file covers:
- partial correlation + Fisher-z behaves sanely
- PC skeleton drops the spurious pair on conditioning
- v-structure orientation + Meek rules produce the expected PDAG
- Defensive fallbacks: <30 samples, K_MAX_COND cap, alpha tuning
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("scipy")

from causality_dag import (                                    # noqa: E402
    DEFAULT_ALPHA, K_MAX_COND, MIN_SAMPLES, PDAG,
    _ci_test, _partial_corr,
    apply_meek_rules, directed_edges, learn_pdag,
    orient_v_structures, pc_skeleton, pdag_causal_pairs,
)


# ── Synthetic generators ──────────────────────────────────────────────


def _common_cause_corpus(n=400, seed=0):
    """A → B and A → C; no direct B↔C link. B and C are pairwise
    correlated (through A) but become independent given A. This is
    the §3.L11 hero corpus.

    Signal/noise ratios are intentionally cleaner than typical log
    data so finite-sample noise doesn't sneak the spurious B-C edge
    past Fisher-z at α=0.01. Real corpora get more bins to compensate.

    Returns a dict mapping cluster_id (int) → np.ndarray time series.
    Cluster ids: 1 = A, 2 = B, 3 = C.
    """
    rng = np.random.RandomState(seed)
    A = rng.normal(0, 1, size=n)
    B = 0.95 * A + rng.normal(0, 0.2, size=n)
    C = 0.95 * A + rng.normal(0, 0.2, size=n)
    return {1: A, 2: B, 3: C}


def _independent_corpus(n=400, seed=0):
    """Three independent series — PC should return no edges."""
    rng = np.random.RandomState(seed)
    return {
        1: rng.normal(0, 1, size=n),
        2: rng.normal(0, 1, size=n),
        3: rng.normal(0, 1, size=n),
    }


def _chain_corpus(n=400, seed=0):
    """A → B → C — a chain. PC should keep A↔B and B↔C and drop A-C
    once conditioned on B."""
    rng = np.random.RandomState(seed)
    A = rng.normal(0, 1, size=n)
    B = 0.95 * A + rng.normal(0, 0.2, size=n)
    C = 0.95 * B + rng.normal(0, 0.2, size=n)
    return {1: A, 2: B, 3: C}


# ── Partial correlation + CI test ─────────────────────────────────────


def test_partial_correlation_pairwise_matches_pearson():
    rng = np.random.RandomState(0)
    x = rng.normal(0, 1, size=200)
    y = 0.7 * x + rng.normal(0, 0.5, size=200)
    pcc = _partial_corr(x, y, np.zeros((200, 0)))
    expected = float(np.corrcoef(x, y)[0, 1])
    assert abs(pcc - expected) < 1e-9


def test_partial_correlation_breaks_via_conditioning_set():
    """The whole point of partial correlation: rho(B, C | A) ≈ 0
    when B and C share only a common cause A."""
    series = _common_cause_corpus()
    A, B, C = series[1], series[2], series[3]
    pair_pcc = _partial_corr(B, C, np.zeros((B.size, 0)))
    cond_pcc = _partial_corr(B, C, A.reshape(-1, 1))
    assert abs(pair_pcc) > 0.5, (
        f"B and C should be pairwise-correlated; got {pair_pcc:.3f}"
    )
    assert abs(cond_pcc) < 0.2, (
        f"B and C should be ~independent given A; got {cond_pcc:.3f}"
    )


def test_ci_test_skips_when_samples_below_min():
    rng = np.random.RandomState(0)
    short = {1: rng.normal(0, 1, size=5), 2: rng.normal(0, 1, size=5)}
    indep, _ = _ci_test(short, 1, 2, [], DEFAULT_ALPHA)
    # Below MIN_SAMPLES the test conservatively returns "not independent"
    # (keeps the edge in the skeleton).
    assert not indep


# ── Skeleton + v-structures ───────────────────────────────────────────


def test_skeleton_drops_spurious_edge_in_common_cause_corpus():
    """The hero skeleton-phase check: B and C must NOT remain
    connected once a conditioning set containing A is tested."""
    series = _common_cause_corpus()
    pdag, sepset = pc_skeleton(series)
    # Edge B (2) — C (3) should have been removed.
    assert not pdag.has_edge(2, 3), "spurious B↔C edge survived skeleton phase"
    # And the sepset for {B, C} should include A (cluster id 1).
    sep_bc = sepset.get(frozenset({2, 3}))
    assert sep_bc is not None
    assert 1 in sep_bc, f"sepset for B,C should include A; got {sep_bc}"
    # The two real edges A-B, A-C should still be there.
    assert pdag.has_edge(1, 2)
    assert pdag.has_edge(1, 3)


def test_independent_corpus_drops_all_edges():
    series = _independent_corpus()
    pdag, _ = pc_skeleton(series)
    # No edges should survive a skeleton over independent variables.
    assert len(pdag.undirected) == 0
    assert len(pdag.directed) == 0


def test_chain_corpus_drops_indirect_a_c_edge():
    series = _chain_corpus()
    pdag, sepset = pc_skeleton(series)
    # A - C edge should be removed once conditioned on B.
    assert not pdag.has_edge(1, 3)
    sep_ac = sepset.get(frozenset({1, 3}))
    assert sep_ac is not None
    assert 2 in sep_ac


# ── V-structure orientation + acceptance gate ─────────────────────────


def test_common_cause_v_structure_does_not_fire():
    """A is a common cause of B and C, NOT a collider. The
    v-structure rule should *not* orient B → A ← C (because A is in
    the sepset for B, C — the rule's exception)."""
    series = _common_cause_corpus()
    pdag, sepset = pc_skeleton(series)
    orient_v_structures(pdag, sepset)
    # The arrow B → A or C → A would be wrong — A is the parent.
    assert (2, 1) not in pdag.directed
    assert (3, 1) not in pdag.directed


def test_acceptance_gate_pc_only_yields_a_to_b_and_a_to_c():
    """The §3.L11 hero gate.

    v1 Granger on this corpus would produce A→B, A→C, B↔C.
    v2 PC must produce A→{B, C} with NO direct B↔C edge.

    The PC algorithm cannot orient A→B vs B→A from observational
    data alone (no v-structure, no time-precedence info baked in
    here). What it MUST do is drop the spurious B-C edge. We
    verify that, plus the structural form of the result."""
    series = _common_cause_corpus()
    pdag = learn_pdag(series)
    pairs = pdag_causal_pairs(pdag)
    # Hero assertion: no B↔C edge in any direction.
    assert (2, 3) not in pairs
    assert (3, 2) not in pairs
    assert not pdag.has_edge(2, 3)
    # A-B and A-C still in the graph (possibly undirected).
    assert pdag.has_edge(1, 2)
    assert pdag.has_edge(1, 3)


def test_directed_edges_extract_helper_returns_sane_shape():
    series = _common_cause_corpus()
    pdag, sepset = pc_skeleton(series)
    orient_v_structures(pdag, sepset)
    apply_meek_rules(pdag)
    edges = directed_edges(pdag, sepset)
    for e in edges:
        assert isinstance(e.src, int)
        assert isinstance(e.dst, int)
        assert isinstance(e.parents_of_dst, list)
        assert isinstance(e.confounders_blocked, list)


# ── Conditioning-set cap ──────────────────────────────────────────────


def test_max_cond_cap_is_respected():
    """With max_cond=0, the algorithm degenerates to pure pairwise
    independence — the B-C edge survives (the very failure mode L11
    is here to fix), which is what we want to be able to demonstrate."""
    series = _common_cause_corpus()
    pdag0, _ = pc_skeleton(series, max_cond=0)
    # B and C are pairwise correlated → skeleton with max_cond=0
    # must retain the edge.
    assert pdag0.has_edge(2, 3), (
        "max_cond=0 should fall back to pairwise; B↔C should survive"
    )
    # And max_cond=1 should be enough to drop B-C (A is a 1-element sepset).
    pdag1, _ = pc_skeleton(series, max_cond=1)
    assert not pdag1.has_edge(2, 3)
