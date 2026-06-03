"""P1.5.2 — Whitelist domain visibility.

User intent: "show only what I pick from Settings."  Inverts the
data model from blacklist (``landing.hidden_domains``) to whitelist
(``landing.visible_domains``).  Defaults to an empty whitelist so
Step 1 stays clean for first-time visitors and shows an inviting
empty state pointing at Settings + the welcome picker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("flask")


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _set_visible(client, visible):
    """Helper: write the new whitelist preference."""
    rv = client.put(
        "/api/preferences",
        json={"landing.visible_domains": visible,
              "landing.hidden_domains":  []},
    )
    assert rv.status_code == 200


# ── /api/templates whitelist semantics ────────────────────────────────


def test_empty_whitelist_means_step_1_grid_is_empty(client):
    _set_visible(client, [])
    data = client.get("/api/templates").get_json()
    assert data["templates"] == []
    assert data["visible"]   == []
    # The full catalogue is still echoed so the onboarding picker
    # (which uses `all`) can still show every option.
    assert len(data["all"]) >= 10


def test_whitelist_filters_to_picked_subset(client):
    _set_visible(client, ["telecom", "healthcare"])
    data = client.get("/api/templates").get_json()
    assert sorted(data["templates"]) == ["healthcare", "telecom"]
    # The hidden list (echoed for legacy UI) is everything NOT picked.
    assert "finance"  in data["hidden"]
    assert "telecom"  not in data["hidden"]


def test_canonical_visible_key_present(client):
    """Going forward, ``visible`` is the canonical key.  Legacy
    consumers can still read ``templates``."""
    _set_visible(client, ["finance"])
    data = client.get("/api/templates").get_json()
    assert data["visible"]   == ["finance"]
    assert data["templates"] == ["finance"]


def test_missing_preference_defaults_to_empty(client):
    """If no visibility preference has ever been set, the whitelist
    is empty — Step 1 stays clean until the user picks."""
    # Wipe both prefs entirely.
    client.put("/api/preferences", json={
        "landing.visible_domains": None,
        "landing.hidden_domains":  None,
    })
    # Some prefs backends return 200 even for None; clear via empty.
    client.put("/api/preferences", json={
        "landing.visible_domains": [],
        "landing.hidden_domains":  [],
    })
    data = client.get("/api/templates").get_json()
    assert data["templates"] == []


# ── Frontend wiring ──────────────────────────────────────────────────


def test_refresh_settings_reads_whitelist(client):
    body = client.get("/wizard").get_data(as_text=True)
    # refreshSettings now treats *checked* as "show", not "hide".
    seg = body.split("async function refreshSettings()", 1)[1] \
              .split("async function saveDomainVisibility()", 1)[0]
    assert "landing.visible_domains" in seg
    # No leftover blacklist reads.
    assert "landing.hidden_domains" not in seg
    # Default is unchecked: only names in the whitelist are checked.
    assert "visible.has(name) ? 'checked' : ''" in seg


def test_save_visibility_writes_whitelist(client):
    body = client.get("/wizard").get_data(as_text=True)
    seg = body.split("async function saveDomainVisibility()", 1)[1] \
              .split("async function pickAllDomains()", 1)[0]
    # The save POST sends visible_domains, with hidden_domains
    # zeroed for back-compat one-way migration.
    assert "landing.visible_domains" in seg
    assert "'landing.hidden_domains':  []" in seg \
        or "'landing.hidden_domains': []" in seg
    # The persisted list = boxes the user TICKED, not unticked.
    assert "b.checked" in seg
    assert "!b.checked" not in seg


def test_settings_help_text_uses_whitelist_language(client):
    body = client.get("/wizard").get_data(as_text=True)
    seg = body.split('id="step-settings"', 1)[1] \
              .split('id="step-evolve"',   1)[0]
    # Honest copy: "tick the ones you want"; "default is none ticked".
    assert "Tick the domains you want" in seg
    assert "nothing is ticked" in seg
    # Old blacklist language must be gone from the Settings panel.
    assert "Uncheck a domain to hide it" not in seg


# ── Step 1 empty-state pointing at Settings ───────────────────────────


def test_step_1_template_grid_has_empty_state(client):
    """When the user has picked nothing, the template grid renders an
    inviting empty state with two paths: open the welcome picker
    or jump to Settings."""
    body = client.get("/wizard").get_data(as_text=True)
    seg = body.split("async function loadTemplateList()", 1)[1] \
              .split("\nasync function loadTemplate(", 1)[0]
    # Branch for "no templates picked yet."
    assert "No starter templates picked yet" in seg
    assert "Open the welcome picker" in seg
    assert "Configure Step 1 in Settings" in seg
    # The picker re-uses the P1.3 onboarding component.
    assert "Onboarding.showNow" in seg
