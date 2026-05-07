"""Suggestion #7 — rule-impact coverage map.

Verifies that compute_coverage correctly attributes rules to classes
across the three signals (slot-fill target, body text, mixed) and that
the wizard endpoint surfaces a usable summary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from wizard.rules import compute_coverage  # noqa: E402


VOCAB = {
    "base_iri": "https://test.example/cov#",
    "classes": [
        {"qname": ":Site",         "label": "Site"},
        {"qname": ":SiteCategory", "label": "Site Category"},
        {"qname": ":Asset",        "label": "Asset"},
        {"qname": ":Customer",     "label": "Customer"},
    ],
    "properties": [
        {"qname": ":hasIncident", "kind": "object"},
    ],
}


def _rule(rid, kind="shacl", body="", meta=None):
    return {"id": rid, "kind": kind, "label": rid, "body": body, "meta": meta}


# ── slot-fill target attribution ─────────────────────────────────────────


def test_slot_fill_target_class_counted():
    rules = [
        _rule("site-flag", meta={
            "target_class": ":Site",
            "conditions": [],
            "assertion": {"path": ":hasIncident", "value": True},
        }),
    ]
    cov = compute_coverage(rules, VOCAB)
    assert cov[":Site"]["count"] == 1
    assert cov[":Site"]["rule_ids"] == ["site-flag"]
    assert cov[":Site"]["details"]["by_target"] == ["site-flag"]
    # No collateral hits.
    assert cov[":Asset"]["count"] == 0


# ── body-text attribution ────────────────────────────────────────────────


def test_sparql_body_mentions_class_counted():
    rules = [
        _rule("reach", kind="sparql", body=(
            "PREFIX : <https://test.example/cov#>\n"
            "CONSTRUCT { ?x :hasIncident true } WHERE { ?x a :Asset }"
        )),
    ]
    cov = compute_coverage(rules, VOCAB)
    assert cov[":Asset"]["count"] == 1
    assert cov[":Asset"]["details"]["by_body"] == ["reach"]


def test_token_boundary_avoids_substring_collisions():
    """`:Site` must NOT match inside `:SiteCategory`."""
    rules = [
        _rule("cat", kind="sparql", body=(
            "PREFIX : <https://test.example/cov#>\n"
            "CONSTRUCT { ?x :hasIncident true } WHERE { ?x a :SiteCategory }"
        )),
    ]
    cov = compute_coverage(rules, VOCAB)
    assert cov[":SiteCategory"]["count"] == 1
    assert cov[":Site"]["count"] == 0


# ── mixed: same rule mentions two classes ────────────────────────────────


def test_rule_can_touch_multiple_classes():
    rules = [
        _rule("multi", kind="sparql", body=(
            "PREFIX : <https://test.example/cov#>\n"
            "CONSTRUCT { ?s :hasIncident ?c } WHERE { ?s a :Site . ?c a :Customer }"
        )),
    ]
    cov = compute_coverage(rules, VOCAB)
    assert cov[":Site"]["count"] == 1
    assert cov[":Customer"]["count"] == 1


def test_target_and_body_both_attribute_but_count_once():
    """A rule whose slot-fill target matches AND whose body text mentions
    the same class still counts as ONE rule for that class."""
    rules = [
        _rule("dual", meta={
            "target_class": ":Site",
            "conditions": [{"path": ":status", "op": "=", "value": "OUTAGE"}],
            "assertion": {"path": ":hasIncident", "value": True},
        }),
    ]
    cov = compute_coverage(rules, VOCAB)
    # The compiled body also contains `:Site` — both signals fire.
    assert cov[":Site"]["count"] == 1
    assert "dual" in cov[":Site"]["details"]["by_target"]
    assert "dual" in cov[":Site"]["details"]["by_body"]


# ── empty / missing inputs ───────────────────────────────────────────────


def test_no_rules_yields_zero_counts():
    cov = compute_coverage([], VOCAB)
    assert all(entry["count"] == 0 for entry in cov.values())
    assert set(cov.keys()) == {":Site", ":SiteCategory", ":Asset", ":Customer"}


def test_unknown_class_in_target_doesnt_explode():
    rules = [_rule("ghost", meta={"target_class": ":NotInVocab",
                                  "assertion": {"path": ":x", "value": True}})]
    cov = compute_coverage(rules, VOCAB)
    # All real classes still report 0 — and the function didn't raise.
    assert all(entry["count"] == 0 for entry in cov.values())


# ── API endpoint smoke ───────────────────────────────────────────────────


def test_route_registers():
    pytest.importorskip("flask")
    pytest.importorskip("flask_cors")
    sys.path.insert(0, str(ROOT))
    import importlib
    app_mod = importlib.import_module("wizard.app")
    rules = {r.rule for r in app_mod.app.url_map.iter_rules()}
    assert "/api/rules/coverage" in rules
