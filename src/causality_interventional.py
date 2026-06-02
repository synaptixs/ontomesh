"""
src/causality_interventional.py — T2.5
──────────────────────────────────────
Interventional causal discovery — labelled deploys / config changes
strengthen the observational PC algorithm.

Why this exists
───────────────
Observational PC (L11 / T1.2) recovers PDAGs — partially directed
acyclic graphs. Some edges remain *undirected* because two DAGs in
the same Markov equivalence class produce indistinguishable
conditional-independence patterns. Without temporal-precedence or
prior structure, the algorithm cannot break the tie.

Interventions break it cleanly. When a node ``X`` is known to
have been *exogenously varied* during a recorded window (a deploy,
a config change, a PagerDuty incident with manual ack), any
observed dependence between ``X`` and a neighbour ``Y`` must be
``X → Y`` — ``Y`` cannot retroactively cause the intervention.

Algorithm
─────────
1. Run the standard observational PC algorithm (skeleton +
   v-structure + Meek). This gives us the PDAG.
2. For every node ``X`` with at least one intervention window:
   a) For each neighbour ``Y``:
      - If the edge is already directed as ``Y → X``, log a conflict
        (the observational data and intervention disagree).
      - Otherwise orient ``X → Y``.
3. Re-run Meek rules — newly directed edges may cascade.
4. Tag every interventionally-oriented edge with metadata so the
   reviewer knows the direction came from a labelled action, not
   correlation.

Public API
──────────
    pdag = learn_pdag_with_interventions(series, interventions)

``interventions`` is ``Dict[node_id, List[(start_bin, end_bin)]]``.
Empty interventions: the function is a no-op wrapper around
``learn_pdag``.

Effort note: full do-calculus identification (Pearl 2009) is out
of scope. This commit ships the simple-but-load-bearing case —
*labelled-source* orientation — which matches the roadmap's
acceptance gate. Heavier identification techniques can layer on
top without breaking this contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


@dataclass
class InterventionalReport:
    """Wraps a PDAG with a record of how each edge was oriented.

    ``interventionally_oriented`` lists ``(src, dst)`` pairs whose
    direction came from an intervention label rather than the
    standard PC orientation rules. ``conflicts`` lists pairs where
    the intervention disagreed with an already-directed
    observational edge (rare; usually a sign of mislabelled data
    or a confounder the PC algorithm couldn't condition on).
    """
    pdag:                      Any                        # causality_dag.PDAG
    interventionally_oriented: List[Tuple[int, int]] = field(default_factory=list)
    conflicts:                 List[Tuple[int, int]] = field(default_factory=list)
    intervention_nodes:        List[int] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "directed":     sorted(self.pdag.directed),
            "undirected":   sorted(self.pdag.undirected),
            "interventionally_oriented": list(self.interventionally_oriented),
            "conflicts":    list(self.conflicts),
            "intervention_nodes": list(self.intervention_nodes),
        }


def learn_pdag_with_interventions(
        series: Dict[Any, Any],
        interventions: Optional[Dict[Any, Sequence[Tuple[int, int]]]] = None,
        *,
        alpha: float = 0.01,
        max_cond: int = 3,
) -> InterventionalReport:
    """End-to-end: observational PC, then interventional orientation.

    ``series`` matches :func:`causality_dag.learn_pdag`'s shape:
    ``Dict[node_id, np.ndarray]``.

    ``interventions`` is ``Dict[node_id, List[(start_bin, end_bin)]]``.
    Empty / None → pure observational behaviour (acceptance-gate
    backwards-compat with L11).
    """
    from causality_dag import learn_pdag, apply_meek_rules

    pdag = learn_pdag(series, alpha=alpha, max_cond=max_cond)
    report = InterventionalReport(pdag=pdag)

    if not interventions:
        return report

    # Filter to nodes that actually appear in the graph AND carry
    # ≥ 1 intervention window. Silently drop labels for nodes
    # we don't have a series for.
    intervened: List = []
    for node, windows in interventions.items():
        if node not in pdag.nodes or not windows:
            continue
        intervened.append(node)
    report.intervention_nodes = list(intervened)

    for src in intervened:
        for nb in list(pdag.neighbours(src)):
            if pdag.is_directed(nb, src):
                # Observational said "nb → src"; intervention says
                # "src → nb". Conflict — surface it for the
                # reviewer, but DON'T silently override the
                # observational decision.
                report.conflicts.append((src, nb))
                continue
            if pdag.is_directed(src, nb):
                continue                              # already oriented our way
            pdag.orient(src, nb)
            report.interventionally_oriented.append((src, nb))

    # Newly directed edges may cascade through Meek's rules — for
    # example, an undirected i — k edge where k now has an
    # interventionally-set parent might fire R1.
    apply_meek_rules(pdag)
    return report


__all__ = ["InterventionalReport", "learn_pdag_with_interventions"]
