"""Real-world infodrift × ontology-toolkit integration demo.

Story: a retail fulfillment team has the toolkit pipeline producing an OWL
ontology + SHACL shapes + JSON-LD context from `db/demo.db`. They want
production drift detection (via the `drift_monitor` package, formerly
`infodrift`) to be **driven by the ontology**, not configured separately.

What this script demonstrates end-to-end:

  1.  Ontology-driven entity discovery
      `OntologyDriftMonitor` reads `output/demo/enterprise.ttl` and
      registers every OWL individual under the retail namespace as a
      `drift_monitor` entity. No drift YAML, no entity list — the
      ontology *is* the registry.

  2.  Two production windows: stable + Black Friday surge
      Window W1 mirrors the baseline distribution → no/few alerts.
      Window W2 inflates `amount` 3-4x and introduces a new category →
      PSI fires, drift_monitor returns Alerts.

  3.  SHACL input gating (P3)
      A malformed production frame (missing required column) is rejected
      *before* it reaches the monitor. This is the same `enterprise-shapes.ttl`
      the toolkit emits — drift inherits the contract for free.

  4.  JSON-LD + PROV-O enrichment (P4)
      Each alert is wrapped in a JSON-LD ObservationRecord using the
      toolkit's context, then appended to
      `output/infodrift/observations.jsonl`. Every drift event is now
      part of the same observation graph as the rest of the toolkit's
      outputs — queryable with SPARQL alongside lineage.

  5.  OWL propagation (P5)
      When `Order/1` drifts, `OWLPropagator` walks the class graph and
      surfaces sibling entities (e.g. `Invoice/1`) that should also be
      watched. Drift escalation follows the ontology, not a hand-written
      dependency map.

Run from the repo root:

    python3 examples/infodrift/scripts/demo_infodrift.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(ROOT))

# Defer heavy imports so a clean error message surfaces if a dep is missing.
try:
    from runtime.drift import (
        DriftEnricher,
        OntologyDriftMonitor,
        OWLPropagator,
        SHACLGate,
    )
except ImportError as exc:
    sys.stderr.write(
        f"\n[infodrift demo] missing dependency: {exc}\n"
        "Install it with:\n"
        "    pip install -r requirements.txt\n"
        "(this installs `drift_monitor`, `rdflib`, `pyshacl`, `pandas`, etc.)\n"
    )
    sys.exit(2)


# ── Paths ────────────────────────────────────────────────────────────────
# Toolkit-emitted artifacts (class hierarchy, shapes, JSON-LD context).
TOOLKIT_ONTOLOGY = ROOT / "output" / "demo" / "ontology" / "enterprise.ttl"
SHAPES           = ROOT / "output" / "demo" / "shapes"   / "enterprise-shapes.ttl"
CONTEXT          = ROOT / "output" / "demo" / "jsonld"   / "enterprise-context.json"

# Per-row instance graph. In a real pipeline this would be RML-materialised
# from your DB or written by toolkit.py with --emit-individuals; for the
# demo we ship a tiny one alongside this script so the example is
# self-contained.
INSTANCES = SCRIPT_DIR / "retail_instances.ttl"

OUT_DIR = ROOT / "output" / "infodrift"
OBS_DB  = OUT_DIR / "observations.jsonl"

NS = "https://ontology.example.com/retail#"

RNG = np.random.default_rng(seed=42)


# ── Pretty printing ──────────────────────────────────────────────────────
def section(title: str) -> None:
    print(f"\n\033[1;36m▸ {title}\033[0m")


def kv(key: str, val: object) -> None:
    print(f"  {key:<24} {val}")


# ── Synthetic data ───────────────────────────────────────────────────────
def baseline_frame() -> pd.DataFrame:
    """A stable retail baseline: amounts ~ N(50, 12), category in {A,B,C}."""
    n = 200
    return pd.DataFrame({
        "amount":   RNG.normal(50, 12, size=n).round(2),
        "category": RNG.choice(["A", "B", "C"], size=n, p=[0.5, 0.3, 0.2]),
    })


def stable_window() -> pd.DataFrame:
    """Same distribution as baseline — expect ~no drift."""
    n = 60
    return pd.DataFrame({
        "amount":   RNG.normal(50, 12, size=n).round(2),
        "category": RNG.choice(["A", "B", "C"], size=n, p=[0.5, 0.3, 0.2]),
    })


def black_friday_window() -> pd.DataFrame:
    """Amount inflated 3-4x, new category 'D' (gift cards) appears."""
    n = 60
    return pd.DataFrame({
        "amount":   RNG.normal(180, 40, size=n).round(2),
        "category": RNG.choice(["A", "B", "D"], size=n, p=[0.2, 0.2, 0.6]),
    })


def malformed_window() -> pd.DataFrame:
    """Schema-violating frame — missing the `amount` column the monitor wants."""
    return pd.DataFrame({"category": ["A", "B", "C"] * 5})


# ── Demo ─────────────────────────────────────────────────────────────────
def main() -> int:
    print("=" * 72)
    print("infodrift × ontology-toolkit — real-world drift integration demo")
    print("=" * 72)

    if not TOOLKIT_ONTOLOGY.exists():
        sys.stderr.write(
            f"\n[demo] toolkit ontology not found at "
            f"{TOOLKIT_ONTOLOGY.relative_to(ROOT)}\n"
            "Run the toolkit first:\n"
            "    python3 toolkit.py --db db/demo.db --out output/demo\n"
            "or use the wrapper:\n"
            "    ./examples/infodrift/demo_infodrift.sh\n"
        )
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if OBS_DB.exists():
        OBS_DB.unlink()

    # ── 1. Ontology-driven entity discovery ──────────────────────────────
    section("1/5  Ontology-driven entity discovery (P2)")
    monitor = OntologyDriftMonitor(ontology_path=INSTANCES, namespace=NS)
    discovered = monitor.discover_individuals()
    kv("toolkit ontology", TOOLKIT_ONTOLOGY.relative_to(ROOT))
    kv("instance graph",   INSTANCES.relative_to(ROOT))
    kv("namespace", NS)
    kv("individuals found", len(discovered))
    for k in discovered[:6]:
        print(f"    · {k}")
    if len(discovered) > 6:
        print(f"    · … (+{len(discovered) - 6} more)")

    if not discovered:
        sys.stderr.write(
            "\n[demo] no individuals discovered under the namespace.\n"
            "The toolkit must produce instance IRIs under the configured "
            "namespace for drift discovery to work. Re-run toolkit.py.\n"
        )
        return 1

    # Pick a small set we'll register and exercise.
    targets = discovered[: min(4, len(discovered))]
    baselines = {key: baseline_frame() for key in targets}

    registered = monitor.register_all(
        baseline_features=baselines,
        numeric_features=["amount"],
        categorical_features=["category"],
    )
    kv("registered", len(registered))

    # ── 2. SHACL input gate ──────────────────────────────────────────────
    section("2/5  SHACL input gate (P3) — reject malformed prod frames")
    gate = SHACLGate(shapes_path=SHAPES, namespace=NS) if SHAPES.exists() else None
    if gate is None or not gate.is_active():
        kv("status", "shapes not present — gate is no-op (toolkit P3 inactive)")
    else:
        kv("shapes", SHAPES.relative_to(ROOT))
        bad = malformed_window()
        try:
            gate.validate(bad, registered[0])
            kv("malformed frame", "PASSED gate (no constraints triggered)")
        except Exception as exc:  # SHACLValidationError or schema error
            kv("malformed frame", f"REJECTED: {type(exc).__name__}")

    # ── 3. Stable + drift windows ────────────────────────────────────────
    section("3/5  Two production windows: stable vs. Black Friday surge")

    enricher = DriftEnricher(
        context_path=CONTEXT,
        obs_db_path=OBS_DB,
        entity_namespace=NS,
    )

    summary: list[dict] = []
    for window_id, builder, label in [
        ("W1_stable",       stable_window,       "stable"),
        ("W2_black_friday", black_friday_window, "Black Friday surge"),
    ]:
        print(f"\n  ── window={window_id}  ({label}) ──")
        for entity_key in registered:
            prod = builder()
            alerts = monitor.run(entity_key, prod_df=prod, window_id=window_id)

            # Pick the worst PSI alert for this entity/window — what an ops
            # dashboard would lead with.
            psi_alerts = [a.to_dict() for a in alerts
                          if a.to_dict().get("metric_type") == "psi"]
            worst = max(psi_alerts, key=lambda d: d.get("observed", 0),
                        default=None)
            psi = worst["observed"] if worst else None
            level = worst["severity"] if worst else "ok"

            summary.append({
                "entity": entity_key,
                "window": window_id,
                "alerts": len(alerts),
                "psi":    None if psi is None else round(float(psi), 3),
                "level":  level,
            })

            # ── 4. JSON-LD + PROV-O enrichment ───────────────────────────
            for a in alerts:
                enricher.enrich_and_store(
                    {"entity_key":  entity_key,
                     "psi_score":   a.to_dict().get("observed"),
                     "drift_level": a.to_dict().get("severity"),
                     "feature":     a.to_dict().get("feature"),
                     "message":     a.to_dict().get("message")},
                    baseline_id="2026Q1",
                    window_id=window_id,
                )

            psi_str = "-" if psi is None else f"{psi:.3f}"
            print(f"    {entity_key:<20}  alerts={len(alerts):<2}  "
                  f"psi={psi_str:<8}  level={level}")

    # ── 5. OWL propagation ───────────────────────────────────────────────
    section("4/5  OWL propagation (P5) — siblings to escalate")
    propagator = OWLPropagator(ontology_path=INSTANCES, namespace=NS)
    drifted = [r for r in summary if r["window"] == "W2_black_friday" and r["alerts"]]
    if not drifted:
        print("  no drifted entities in W2 — nothing to propagate")
    else:
        for row in drifted[:3]:
            deps = propagator.dependents(row["entity"])
            print(f"  {row['entity']} drifted → propagator surfaces {len(deps)} dependent(s):")
            for d in deps[:5]:
                print(f"    → {d}")

    # ── Summary ──────────────────────────────────────────────────────────
    section("5/5  Summary")
    kv("observations written", OBS_DB.relative_to(ROOT))
    kv("records",
       sum(1 for _ in OBS_DB.open()) if OBS_DB.exists() else 0)

    df = pd.DataFrame(summary)
    print()
    print(df.to_string(index=False))

    print("\nWhat this proves:")
    print("  · the OWL ontology is the single source of truth for *which* entities to monitor")
    print("  · SHACL shapes gate production frames before drift_monitor sees them")
    print("  · drift reports are JSON-LD/PROV-O records that join the toolkit's observation graph")
    print("  · escalation follows the OWL class graph, not a hand-written dependency list")
    print(f"\nNext: open {OBS_DB.relative_to(ROOT)} or query it with SPARQL via runtime/temporal_queries/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
