"""
causality_dag.py — Phase L11
────────────────────────────
PC algorithm for causal structure learning over template rate series.

Why this exists
───────────────
The v1 ``causality_miner`` tests Granger and transfer-entropy between
**pairs** of template rate series in isolation. That misses shared
upstream causes: if a NetworkPartition causes both ServiceADown and
ServiceBDown, the pairwise test will also report a spurious
ServiceADown → ServiceBDown edge. A reviewer chasing that bogus edge
spends time on a structural artifact rather than the actual root cause.

The PC algorithm (Spirtes & Glymour 1991; Bishop §8.2, §8.4.5) discovers
the **structure** of the dependency graph by testing conditional
independence under expanding conditioning sets. An edge ``X — Y``
survives only if **no** subset of the other variables makes ``X ⊥ Y``.
The shared-cause artifact dies as soon as we condition on the cause.

The output is a Partially Directed Acyclic Graph (PDAG) — some edges
are oriented as a result of v-structure detection + Meek rule
propagation; others remain undirected (Markov-equivalence-class
ambiguity). Downstream, ``seed_from_mining`` treats directed edges
as causal proposals and undirected edges as relationships.

Method
──────
1. **Skeleton phase.** Start with a complete undirected graph over
   the template cluster ids. For each (X, Y) edge, search for a
   conditioning set ``Z`` (subset of neighbours, size 0..K_MAX_COND)
   such that ``X ⊥ Y | Z``. If one is found, drop the edge and record
   ``Z`` in ``sepset[(X, Y)]``.
2. **V-structure orientation.** For every unshielded triple
   ``X — K — Y`` (i.e. X and Y are not adjacent), orient as
   ``X → K ← Y`` iff ``K ∉ sepset[(X, Y)]``.
3. **Meek rule propagation.** Apply rules R1-R4 to propagate
   orientations without introducing new v-structures or cycles.

Conditional-independence test
─────────────────────────────
Partial Pearson correlation followed by Fisher's z-transform — the
standard CI test for continuous data with a Gaussian-ish marginal
structure, which template rate series approximately have once
binned. For a regularised-regression-based partial correlation:

    ρ_{XY·Z} = corr(X | Z, Y | Z)
    z = atanh(ρ) * sqrt(n - |Z| - 3)
    accept H0 (independence) iff |z| < Φ^{-1}(1 - α/2)

Risk mitigations per §6
───────────────────────
- ``K_MAX_COND = 3`` — caps conditioning-set size so CI tests stay
  polynomial. Spirtes & Glymour cite this as the standard practical
  ceiling for log-corpus-scale problems.
- ``MIN_SAMPLES = 30`` — skip CI tests when the series have fewer
  than this many time bins; the partial-correlation test becomes
  unreliable below that.
- ``alpha = 0.01`` (default) — conservative, biases the algorithm
  toward retaining edges when there isn't strong evidence to drop
  them. Reviewers can always reject; spurious edges are cheaper
  than missing edges in this corpus.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
from scipy.stats import norm


# Defaults — per §6 mitigations.
K_MAX_COND = 3
MIN_SAMPLES = 30
DEFAULT_ALPHA = 0.01


# ── Partial correlation CI test ──────────────────────────────────────────


def _partial_corr(x: np.ndarray, y: np.ndarray, Z: np.ndarray
                  ) -> float:
    """Pearson partial correlation of x and y given the columns of Z
    (Z shape: (n, k) where k = |conditioning set|, possibly k=0).

    Computed via residuals from OLS regression on Z. For k=0 this
    reduces to plain Pearson correlation."""
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if Z is None or Z.size == 0:
        if x.std() == 0 or y.std() == 0:
            return 0.0
        return float(np.corrcoef(x, y)[0, 1])
    # Append intercept; least-squares solve for residuals.
    Z_design = np.hstack([Z, np.ones((Z.shape[0], 1))])
    try:
        bx, *_ = np.linalg.lstsq(Z_design, x, rcond=None)
        by, *_ = np.linalg.lstsq(Z_design, y, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    rx = x - Z_design @ bx
    ry = y - Z_design @ by
    if rx.std() == 0 or ry.std() == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def _ci_test(series: Dict[int, np.ndarray],
             i: int, j: int, cond: Sequence[int],
             alpha: float) -> Tuple[bool, float]:
    """Test whether ``X_i ⊥ X_j | X_{cond}`` at level ``alpha``.

    Returns ``(is_independent, p_value)``. ``p_value`` is the
    two-sided Fisher-z p-value (larger ⇒ more evidence of
    independence)."""
    x = series[i]
    y = series[j]
    n = min(x.size, y.size)
    if n < MIN_SAMPLES:
        # Inadequate sample size — be conservative and report
        # *not* independent (retain the edge).
        return False, 0.0
    x = x[:n]
    y = y[:n]
    if cond:
        Z = np.column_stack([series[k][:n] for k in cond])
    else:
        Z = np.zeros((n, 0))
    rho = _partial_corr(x, y, Z)
    # Numerical guard against |rho|==1 in atanh.
    rho = max(-0.999999, min(0.999999, rho))
    df = n - len(cond) - 3
    if df <= 0:
        return False, 0.0
    z = math.atanh(rho) * math.sqrt(df)
    # Two-sided p-value under N(0,1).
    p = 2.0 * (1.0 - norm.cdf(abs(z)))
    return p > alpha, float(p)


# ── PDAG data structure ──────────────────────────────────────────────────


@dataclass
class PDAG:
    """Mixed directed / undirected graph over int node ids.

    ``directed[(u, v)]`` means u → v.
    ``undirected`` holds (u, v) with u < v.
    """
    nodes: List[int]
    directed: Set[Tuple[int, int]] = field(default_factory=set)
    undirected: Set[Tuple[int, int]] = field(default_factory=set)

    def has_edge(self, u: int, v: int) -> bool:
        return ((u, v) in self.directed
                or (v, u) in self.directed
                or (min(u, v), max(u, v)) in self.undirected)

    def is_directed(self, u: int, v: int) -> bool:
        return (u, v) in self.directed

    def neighbours(self, u: int) -> Set[int]:
        out: Set[int] = set()
        for (a, b) in self.directed:
            if a == u:
                out.add(b)
            elif b == u:
                out.add(a)
        for (a, b) in self.undirected:
            if a == u:
                out.add(b)
            elif b == u:
                out.add(a)
        return out

    def parents(self, u: int) -> Set[int]:
        """Confirmed directed parents only (excludes undirected
        neighbours)."""
        return {a for (a, b) in self.directed if b == u}

    def add_undirected(self, u: int, v: int) -> None:
        if u == v:
            return
        self.undirected.add((min(u, v), max(u, v)))

    def remove_edge(self, u: int, v: int) -> None:
        self.directed.discard((u, v))
        self.directed.discard((v, u))
        self.undirected.discard((min(u, v), max(u, v)))

    def orient(self, u: int, v: int) -> None:
        """Convert an undirected edge u-v into u→v. No-op if already
        directed in either direction. Removes the undirected pair."""
        self.undirected.discard((min(u, v), max(u, v)))
        if (v, u) in self.directed:
            # Conflict — leave alone; some Meek rules will request
            # both orientations on opposite passes.
            return
        self.directed.add((u, v))


# ── Skeleton phase ───────────────────────────────────────────────────────


def pc_skeleton(series: Dict[int, np.ndarray],
                *, alpha: float = DEFAULT_ALPHA,
                max_cond: int = K_MAX_COND,
                ) -> Tuple[PDAG, Dict[FrozenSet[int], FrozenSet[int]]]:
    """Build the PC skeleton + sepsets over the rate-series nodes.

    Returns ``(pdag, sepset)`` — at this stage ``pdag.directed`` is
    empty and all edges are in ``undirected``. ``sepset`` maps a
    frozenset ``{i, j}`` of dropped-edge endpoints to the set of
    conditioning variables that broke the dependence (used by the
    v-structure step)."""
    nodes = sorted(series.keys())
    pdag = PDAG(nodes=list(nodes))
    sepset: Dict[FrozenSet[int], FrozenSet[int]] = {}

    # Start with the complete undirected graph.
    for i, j in itertools.combinations(nodes, 2):
        pdag.add_undirected(i, j)

    # Iterate over conditioning-set size from 0 up to max_cond. At
    # each level, for each remaining edge, search the smaller
    # endpoint's neighbours (minus the other endpoint) for a
    # conditioning subset that breaks the edge.
    for level in range(0, max_cond + 1):
        # Snapshot edges so we can mutate while iterating.
        current = list(pdag.undirected)
        for (i, j) in current:
            if (i, j) not in pdag.undirected:
                continue
            cand_pool = pdag.neighbours(i) - {j}
            if len(cand_pool) < level:
                continue
            broken = False
            for cond in itertools.combinations(sorted(cand_pool), level):
                indep, _p = _ci_test(series, i, j, list(cond), alpha)
                if indep:
                    pdag.remove_edge(i, j)
                    sepset[frozenset((i, j))] = frozenset(cond)
                    broken = True
                    break
            if broken:
                continue
            # Symmetric search from j's neighbours when i's pool ran out.
            cand_pool_j = pdag.neighbours(j) - {i}
            if len(cand_pool_j) < level:
                continue
            for cond in itertools.combinations(sorted(cand_pool_j), level):
                indep, _p = _ci_test(series, i, j, list(cond), alpha)
                if indep:
                    pdag.remove_edge(i, j)
                    sepset[frozenset((i, j))] = frozenset(cond)
                    break

    return pdag, sepset


# ── V-structure orientation ──────────────────────────────────────────────


def orient_v_structures(pdag: PDAG,
                        sepset: Dict[FrozenSet[int], FrozenSet[int]]
                        ) -> None:
    """For every unshielded triple ``X — K — Y`` (X not adjacent to
    Y), orient as ``X → K ← Y`` iff K ∉ sepset[(X, Y)]. Mutates
    ``pdag`` in place."""
    nodes = list(pdag.nodes)
    triples = []
    for k in nodes:
        nbrs = sorted(pdag.neighbours(k))
        for i, j in itertools.combinations(nbrs, 2):
            if not pdag.has_edge(i, j):
                triples.append((i, k, j))

    for (i, k, j) in triples:
        sep = sepset.get(frozenset((i, j)))
        if sep is None:
            continue
        if k in sep:
            continue
        # Orient both halves as colliders into k.
        pdag.orient(i, k)
        pdag.orient(j, k)


# ── Meek rules ───────────────────────────────────────────────────────────


def apply_meek_rules(pdag: PDAG, max_iter: int = 200) -> None:
    """Apply Meek's rules R1-R4 until the graph is stable or
    ``max_iter`` passes complete.

    R1: i → k - j  with i not adj j  ⇒  k → j  (no new v-structure)
    R2: i → k → j  with i - j        ⇒  i → j  (no cycle)
    R3: i - j, two parents of j (a, b) both undirected-adj to i and
        not adj each other  ⇒  i → j
    R4: similar with a directed link via a fourth node
    """
    for _ in range(max_iter):
        changed = False

        # R1
        for (i, k) in list(pdag.directed):
            for j in list(pdag.neighbours(k)):
                if j == i:
                    continue
                if pdag.is_directed(k, j) or pdag.is_directed(j, k):
                    continue
                if (min(k, j), max(k, j)) not in pdag.undirected:
                    continue
                if not pdag.has_edge(i, j):
                    pdag.orient(k, j)
                    changed = True

        # R2
        for (i, k) in list(pdag.directed):
            for j in list(pdag.neighbours(k)):
                if not pdag.is_directed(k, j):
                    continue
                if (min(i, j), max(i, j)) in pdag.undirected:
                    pdag.orient(i, j)
                    changed = True

        # R3
        for (a, j) in list(pdag.directed):
            for (b, j2) in list(pdag.directed):
                if j != j2 or a == b:
                    continue
                # Both a and b point to j. Need a node i s.t.
                # i - a, i - b, i - j, a not adj b.
                for i in list(pdag.neighbours(j)):
                    if i in (a, b):
                        continue
                    if (min(i, j), max(i, j)) not in pdag.undirected:
                        continue
                    if (min(i, a), max(i, a)) not in pdag.undirected:
                        continue
                    if (min(i, b), max(i, b)) not in pdag.undirected:
                        continue
                    if pdag.has_edge(a, b):
                        continue
                    pdag.orient(i, j)
                    changed = True

        # R4 — chordal-friendly Meek rule. Implemented in the
        # canonical form: if i - j, i - k, k - l, k → j, l → j,
        # and i not adj l, orient i → j. Rarely fires on small
        # template-rate graphs but kept for completeness.
        for (k, j) in list(pdag.directed):
            for (l, j2) in list(pdag.directed):
                if j != j2 or k == l:
                    continue
                if (min(k, l), max(k, l)) not in pdag.undirected:
                    continue
                for i in list(pdag.neighbours(j)):
                    if i in (k, l):
                        continue
                    if (min(i, j), max(i, j)) not in pdag.undirected:
                        continue
                    if (min(i, k), max(i, k)) not in pdag.undirected:
                        continue
                    if pdag.has_edge(i, l):
                        continue
                    pdag.orient(i, j)
                    changed = True

        if not changed:
            return


# ── Top-level PDAG learner ───────────────────────────────────────────────


def learn_pdag(series: Dict[int, np.ndarray],
               *, alpha: float = DEFAULT_ALPHA,
               max_cond: int = K_MAX_COND,
               ) -> PDAG:
    """End-to-end PC algorithm: skeleton → v-structures → Meek.
    Returns the final PDAG."""
    pdag, sepset = pc_skeleton(series, alpha=alpha, max_cond=max_cond)
    orient_v_structures(pdag, sepset)
    apply_meek_rules(pdag)
    return pdag


# ── Surfacing the PDAG to seed_from_mining ───────────────────────────────


@dataclass
class PdagEdge:
    """Convenience wrapper for an oriented PDAG edge with the parent
    set and shared-cause hint that the wizard UI renders. Cluster ids
    are the integer template ids in ``log_templates``."""
    src: int
    dst: int
    parents_of_dst: List[int]                    # for shared-cause hint
    confounders_blocked: List[int]               # cond. set that killed
                                                 # any spurious pair
                                                 # involving this edge


def directed_edges(pdag: PDAG,
                   sepset: Optional[Dict[FrozenSet[int], FrozenSet[int]]] = None
                   ) -> List[PdagEdge]:
    """Extract directed edges + the shared-cause / blocked-confounder
    hints. Optional ``sepset`` (from ``pc_skeleton``) lets us list the
    conditioning sets that the v1 pairwise test would have missed
    — that's the 'shared upstream cause' line the UI shows."""
    out: List[PdagEdge] = []
    for (u, v) in sorted(pdag.directed):
        parents_of_v = sorted(pdag.parents(v) - {u})
        confounders: List[int] = []
        if sepset is not None:
            # Any sepset that points to a common ancestor of u or v is
            # a confounder we successfully blocked.
            for key, sep in sepset.items():
                if u in key and sep:
                    confounders.extend(sep)
        out.append(PdagEdge(
            src=int(u), dst=int(v),
            parents_of_dst=[int(p) for p in parents_of_v],
            confounders_blocked=sorted(set(int(c) for c in confounders)),
        ))
    return out


def pdag_causal_pairs(pdag: PDAG) -> Set[Tuple[int, int]]:
    """Set of (src, dst) directed edges from the PDAG. Convenient
    for ``seed_from_mining``'s causal-pairs intersection check."""
    return {(int(u), int(v)) for (u, v) in pdag.directed}


__all__ = [
    "PDAG", "PdagEdge",
    "K_MAX_COND", "MIN_SAMPLES", "DEFAULT_ALPHA",
    "pc_skeleton", "orient_v_structures", "apply_meek_rules",
    "learn_pdag", "directed_edges", "pdag_causal_pairs",
]
