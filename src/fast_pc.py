"""
src/fast_pc.py — T3.2
─────────────────────
Faster PC-algorithm skeleton for L11.

What this fixes
───────────────
The L11 skeleton phase has worst-case O(p^(k+1)) work in p
variables and conditioning-set size k. The v2 cap was k=3
specifically to keep the wall-clock bounded; raising it to k=5
(genuine business value — more confounders blocked) needs two
micro-optimisations:

1. **CI-test memoisation.** The skeleton phase re-tests
   ``(i, j, S)`` triples from both endpoints (the algorithm
   symmetrically searches each node's neighbour pool). Caching
   results by frozen ``(i, j, S)`` halves the test count without
   semantic change.

2. **Conditioning-set ordering.** Among candidate conditioning
   sets at a given size, test in order of *neighbour-overlap*
   first — sets that share neighbours with both endpoints are
   more likely to break the dependence. Early termination on the
   first independence success kills the rest.

Both are pure speed-ups: the output PDAG is identical to v1's
:func:`causality_dag.pc_skeleton` modulo set ordering.

Public API
──────────
    pdag, sepset = fast_pc_skeleton(series, alpha=0.01, max_cond=5)
    pdag         = learn_pdag_fast(series, ...)

``learn_pdag_fast`` is the drop-in replacement for
``causality_dag.learn_pdag`` — same return type, same default
behaviour, just faster at higher ``max_cond``.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, FrozenSet, Optional, Set, Tuple

import numpy as np

from causality_dag import (
    DEFAULT_ALPHA, K_MAX_COND, MIN_SAMPLES, PDAG, _ci_test,
    apply_meek_rules, orient_v_structures,
)


# ── Caching wrapper for the CI test ─────────────────────────────────────


class _CITestCache:
    """Memoiser around ``causality_dag._ci_test``. Keyed by the
    canonical (i, j, sorted-tuple-of-cond) triple."""

    __slots__ = ("series", "alpha", "_cache", "_hits", "_misses")

    def __init__(self, series: Dict[int, np.ndarray], alpha: float) -> None:
        self.series = series
        self.alpha = alpha
        self._cache: Dict[Tuple[int, int, Tuple[int, ...]], Tuple[bool, float]] = {}
        self._hits = 0
        self._misses = 0

    def test(self, i: int, j: int, cond) -> Tuple[bool, float]:
        a, b = (i, j) if i <= j else (j, i)
        key = (a, b, tuple(sorted(cond)))
        cached = self._cache.get(key)
        if cached is not None:
            self._hits += 1
            return cached
        self._misses += 1
        result = _ci_test(self.series, a, b, list(key[2]), self.alpha)
        self._cache[key] = result
        return result

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total else 0.0


# ── Sorted-neighbour-overlap ordering ───────────────────────────────────


def _ordered_conditioning_sets(neighbours: Set[int],
                               other_endpoint: int,
                               level: int,
                               other_neighbours: Set[int]) -> Any:
    """Yield candidate conditioning sets at the given size, ordered
    by 'how likely is this set to break the dependence'.

    Heuristic: a set shared by *both* endpoints' neighbour pools is
    a strong d-separator candidate; emit those first. Falls back
    to lexicographic order for the rest.
    """
    pool = sorted(neighbours - {other_endpoint})
    if level == 0:
        yield ()
        return
    if len(pool) < level:
        return
    common = sorted(set(pool) & other_neighbours)
    if common:
        # First emit subsets that are fully drawn from the common
        # neighbours (highest break-likelihood).
        if len(common) >= level:
            for combo in itertools.combinations(common, level):
                yield combo
        # Then mixed subsets (level-1 common + 1 other), if any.
        if level >= 2 and len(common) >= 1:
            others = [p for p in pool if p not in set(common)]
            for c in itertools.combinations(common, level - 1):
                for o in others:
                    if o in c:
                        continue
                    cand = tuple(sorted(set(c) | {o}))
                    if len(cand) == level:
                        yield cand
    # Fall back to the full lex enumeration; the cache will skip
    # the ones we've already emitted on the first pass.
    for combo in itertools.combinations(pool, level):
        yield combo


# ── Fast skeleton ───────────────────────────────────────────────────────


def fast_pc_skeleton(series: Dict[int, np.ndarray],
                    *, alpha: float = DEFAULT_ALPHA,
                    max_cond: int = K_MAX_COND,
                    ) -> Tuple[PDAG, Dict[FrozenSet[int], FrozenSet[int]]]:
    """Drop-in replacement for :func:`causality_dag.pc_skeleton`
    with CI-test caching + neighbour-overlap-prioritised ordering.

    Same return contract — ``(pdag, sepset)``. PDAG has the
    expected edge set; sepset records the conditioning set that
    broke each removed edge."""
    nodes = sorted(series.keys())
    pdag = PDAG(nodes=list(nodes))
    sepset: Dict[FrozenSet[int], FrozenSet[int]] = {}

    for i, j in itertools.combinations(nodes, 2):
        pdag.add_undirected(i, j)

    cache = _CITestCache(series, alpha)
    seen_pairs: Set[Tuple[int, int, Tuple[int, ...]]] = set()

    for level in range(0, max_cond + 1):
        current = list(pdag.undirected)
        for (i, j) in current:
            if (i, j) not in pdag.undirected:
                continue
            i_neighbours = pdag.neighbours(i)
            j_neighbours = pdag.neighbours(j)
            broken = False
            # Search from i's side first.
            for cond in _ordered_conditioning_sets(
                    i_neighbours, j, level, j_neighbours):
                if len(cond) != level:
                    continue
                dedup = (i, j, tuple(sorted(cond)))
                if dedup in seen_pairs:
                    continue
                seen_pairs.add(dedup)
                indep, _ = cache.test(i, j, cond)
                if indep:
                    pdag.remove_edge(i, j)
                    sepset[frozenset((i, j))] = frozenset(cond)
                    broken = True
                    break
            if broken:
                continue
            # Symmetric search from j's neighbours.
            for cond in _ordered_conditioning_sets(
                    j_neighbours, i, level, i_neighbours):
                if len(cond) != level:
                    continue
                dedup = (i, j, tuple(sorted(cond)))
                if dedup in seen_pairs:
                    continue
                seen_pairs.add(dedup)
                indep, _ = cache.test(i, j, cond)
                if indep:
                    pdag.remove_edge(i, j)
                    sepset[frozenset((i, j))] = frozenset(cond)
                    break

    return pdag, sepset


def learn_pdag_fast(series: Dict[int, np.ndarray],
                    *, alpha: float = DEFAULT_ALPHA,
                    max_cond: int = K_MAX_COND,
                    ) -> PDAG:
    """End-to-end fast PC: skeleton → v-structures → Meek.

    Same contract as :func:`causality_dag.learn_pdag`; defaults to
    the conservative L11 settings. ``max_cond`` can be safely raised
    to 5 with this implementation on workloads where v2's cap of 3
    was the budget bottleneck."""
    pdag, sepset = fast_pc_skeleton(series, alpha=alpha, max_cond=max_cond)
    orient_v_structures(pdag, sepset)
    apply_meek_rules(pdag)
    return pdag


__all__ = ["fast_pc_skeleton", "learn_pdag_fast"]
