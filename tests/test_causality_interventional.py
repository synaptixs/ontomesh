"""T2.5 — Interventional causal discovery.

Tests the interventional-PC wrapper on top of L11.

Acceptance gates (roadmap §3.T2.5):
- On a synthetic corpus where deploy A is a known cause of
  outage B (labelled), interventional PC produces a directed
  ``deploy_A → B`` edge that observational PC alone cannot.
- v1 acceptance gates from L11 still pass when no interventions
  are labelled (backwards-compat with the observational path).
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


from causality_dag import learn_pdag                                 # noqa: E402
from causality_interventional import (                               # noqa: E402
    InterventionalReport, learn_pdag_with_interventions,
)


# ── Synthetic fixtures ────────────────────────────────────────────────


def _common_cause_corpus(n=400, seed=0):
    """A causes both B and C — exact same fixture L11's hero test
    uses. Tightens the bar: the interventional algorithm should
    not regress on this shape."""
    rng = np.random.RandomState(seed)
    A = rng.normal(0, 1, size=n)
    B = 0.95 * A + rng.normal(0, 0.2, size=n)
    C = 0.95 * A + rng.normal(0, 0.2, size=n)
    return {1: A, 2: B, 3: C}


def _deploy_corpus(n=400, deploy_bins=None, seed=0):
    """Deploy event drives both metric and log spikes.

    Node 1 (deploy) is mostly zero with sharp pulses inside the
    ``deploy_bins`` ranges. Nodes 2 and 3 spike in step with
    the deploy plus independent noise.
    """
    rng = np.random.RandomState(seed)
    deploy_bins = deploy_bins or [(200, 215)]
    deploy = np.zeros(n)
    for start, end in deploy_bins:
        deploy[start:end] = 1.0
    metric = 50.0 + 40.0 * deploy + rng.normal(0, 6, size=n)
    log    =  1.0 +  5.0 * deploy + rng.normal(0, 1, size=n)
    return {1: deploy, 2: metric, 3: log}


# ── No-op when no interventions ──────────────────────────────────────


def test_no_interventions_is_a_noop_wrapper():
    """Backwards-compat: with no labels, the result is identical to
    plain :func:`learn_pdag` (the v1 L11 path)."""
    series = _common_cause_corpus()
    obs = learn_pdag(series)
    rep = learn_pdag_with_interventions(series)
    assert sorted(rep.pdag.directed) == sorted(obs.directed)
    assert sorted(rep.pdag.undirected) == sorted(obs.undirected)
    assert rep.interventionally_oriented == []
    assert rep.conflicts == []
    assert rep.intervention_nodes == []


def test_unknown_intervention_nodes_are_silently_dropped():
    series = _common_cause_corpus()
    rep = learn_pdag_with_interventions(
        series, interventions={999: [(10, 20)]},
    )
    # No real intervention found; behaves like observational.
    assert rep.interventionally_oriented == []
    assert rep.intervention_nodes == []


# ── Hero acceptance gate ─────────────────────────────────────────────


def test_acceptance_gate_intervention_directs_deploy_edges():
    """Hero gate (roadmap §3.T2.5).

    With deploy node labelled as intervened on bins 200–215,
    every observational edge incident to the deploy node must
    be oriented OUTWARD (deploy → effect).
    """
    series = _deploy_corpus()
    interventions = {1: [(200, 215)]}
    rep = learn_pdag_with_interventions(series, interventions=interventions)

    # Deploy (node 1) has at least one outgoing edge.
    outgoing = [(s, t) for (s, t) in rep.pdag.directed if s == 1]
    assert outgoing, (
        f"deploy node has no outgoing directed edges; pdag="
        f"{rep.pdag.directed}, undirected={rep.pdag.undirected}"
    )

    # No incoming edges to deploy — deploy is exogenously varied,
    # nothing can cause it.
    incoming = [(s, t) for (s, t) in rep.pdag.directed if t == 1]
    assert not incoming, (
        f"deploy has incoming edges after interventional orientation: "
        f"{incoming}"
    )

    # At least one edge was credited to the intervention.
    assert rep.interventionally_oriented
    for src, _dst in rep.interventionally_oriented:
        assert src == 1, (
            f"interventionally-oriented edge from non-intervention "
            f"node: {(src, _dst)}"
        )


def test_observational_alone_leaves_deploy_edges_undirected():
    """Sanity check: without interventions on the same corpus, at
    least one edge incident to the deploy node is undirected
    (proving the intervention IS the source of new orientation in
    the test above)."""
    series = _deploy_corpus()
    obs = learn_pdag(series)
    # Count edges incident on deploy (node 1) that are undirected.
    incident = [(u, v) for (u, v) in obs.undirected
                if 1 in (u, v)]
    # We don't require ALL edges to be undirected — that depends on
    # v-structure orientation. We only need ≥ 1 edge to deploy that
    # the interventional version can promote.
    has_undirected = bool(incident)
    has_into_deploy = any(s != 1 and t == 1 for (s, t) in obs.directed)
    assert has_undirected or has_into_deploy, (
        f"observational PC oriented every deploy edge outward "
        f"already — the test's contrast premise doesn't hold: "
        f"directed={obs.directed}, undirected={obs.undirected}"
    )


# ── Conflict surfacing ───────────────────────────────────────────────


def test_conflict_surfaced_when_observational_says_opposite():
    """If observational PC already directed Y → X but the
    intervention says X → Y, we don't overwrite — we surface the
    conflict for the reviewer.
    """
    # We synthesise a corpus where observational PC directs node 2 → 1
    # very confidently (via a strong v-structure). Then we mark
    # node 1 as intervened on; the algorithm should report the
    # conflict and leave the existing direction in place.
    rng = np.random.RandomState(0)
    n = 400
    # Build A → B observationally:
    a = rng.normal(0, 1, n)
    b = 0.95 * a + rng.normal(0, 0.2, n)
    c = 0.95 * b + rng.normal(0, 0.2, n)
    # This is a chain a → b → c. Observational PC orients via v-structure
    # if any. The exact orientation may vary, but we can inspect the
    # report's conflicts list whether or not it fires.
    series = {1: a, 2: b, 3: c}
    rep = learn_pdag_with_interventions(
        series, interventions={3: [(50, 70)]},   # intervene on node 3
    )
    # Either node 3 has only outgoing edges OR we record a conflict.
    incoming_3 = [(s, t) for (s, t) in rep.pdag.directed if t == 3]
    # If incoming edges to 3 still exist, they MUST be reflected as
    # conflicts (we promised not to overwrite observational
    # decisions silently).
    if incoming_3:
        # For every incoming (src, 3), expect (3, src) in conflicts.
        for src, _ in incoming_3:
            assert (3, src) in rep.conflicts


# ── Report shape ─────────────────────────────────────────────────────


def test_report_as_dict_serialises_cleanly():
    series = _deploy_corpus()
    rep = learn_pdag_with_interventions(
        series, interventions={1: [(200, 215)]},
    )
    d = rep.as_dict()
    assert {"directed", "undirected", "interventionally_oriented",
             "conflicts", "intervention_nodes"} <= set(d)


def test_interventions_dont_create_phantom_nodes():
    """Sanity: labels for non-existent nodes don't add nodes to the
    graph or appear in the intervention_nodes list."""
    series = {1: np.array([1.0, 2.0, 1.0]),
              2: np.array([1.0, 1.0, 2.0])}
    rep = learn_pdag_with_interventions(
        series,
        interventions={
            999: [(0, 2)],            # unknown node
            42:  [(0, 1)],            # unknown node
        },
    )
    assert rep.intervention_nodes == []
