"""P1.5.1 — Settings: switch starting point + honest visibility labels.

User report: "configuration setting is broken or not visible to pick
different domain."

Root cause: the Settings step had only a "Domain visibility" checkbox
grid that *hid* templates from Step 1, with confusing copy that said
"landing page" (which after P1.2 means the marketing site, not the
wizard).  There was no positive action to *load* a different starting
point.  A prior session had also flipped 9 of 10 domains to hidden,
leaving only Healthcare visible on Step 1.

These tests verify the fix: a "Switch starting point" card opens the
P1.3 onboarding modal on demand, the visibility card uses honest
"Step 1" copy, and a "Show all" button restores every domain.
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


# ── New "Switch starting point" card ──────────────────────────────────


def test_settings_has_switch_starting_point_card(client):
    body = client.get("/wizard").get_data(as_text=True)
    # Locate the settings panel and assert the new card is inside.
    seg = body.split('id="step-settings"', 1)[1].split('id="step-evolve"', 1)[0]
    assert "Switch starting point" in seg
    assert "reopenOnboarding()" in seg
    # The secondary path (Load a saved ontology) is also offered.
    assert "goStep('library')" in seg


def test_reopen_onboarding_fn_resets_and_force_shows(client):
    body = client.get("/wizard").get_data(as_text=True)
    # Function declared at module scope.
    assert "function reopenOnboarding()" in body
    seg = body.split("function reopenOnboarding()", 1)[1].split("\n}\n", 1)[0]
    # Clears the dismissed flag so the modal isn't no-op'd.
    assert "Onboarding.reset()" in seg
    # And force-shows with template-pick + skip callbacks.
    assert "Onboarding.showNow" in seg
    assert "/api/template/"     in seg
    assert "goStep('entities')" in seg


# ── Honest visibility copy ────────────────────────────────────────────


def test_visibility_copy_no_longer_says_landing_page(client):
    """The marketing landing page is at /; the Settings copy used to
    say 'landing-page template grid' which is now actively misleading."""
    body = client.get("/wizard").get_data(as_text=True)
    seg = body.split('id="step-settings"', 1)[1].split('id="step-evolve"', 1)[0]
    # Old misleading phrase must be gone from Settings.
    assert "landing-page template grid" not in seg
    # New honest phrase references Step 1 explicitly.
    assert "Step 1" in seg
    # And explicitly tells the user the marketing landing isn't affected.
    assert "marketing landing" in seg


def test_settings_subtitle_describes_real_actions(client):
    body = client.get("/wizard").get_data(as_text=True)
    seg = body.split('id="step-settings"', 1)[1].split('id="step-evolve"', 1)[0]
    # The subtitle now lists what Settings actually does for the user.
    assert "Switch starting points" in seg
    assert "Step 1" in seg


# ── "Show all" reset ──────────────────────────────────────────────────


def test_settings_has_pick_all_and_clear(client):
    """P1.5.2 — whitelist convenience buttons.  'Pick all' ticks every
    box and saves; 'Clear' unticks every box and saves."""
    body = client.get("/wizard").get_data(as_text=True)
    seg = body.split('id="step-settings"', 1)[1].split('id="step-evolve"', 1)[0]
    assert 'onclick="pickAllDomains()"' in seg
    assert 'onclick="clearDomainPicks()"' in seg
    assert "Pick all" in seg
    assert "Clear"    in seg


def test_pick_all_fn_checks_everything_and_saves(client):
    body = client.get("/wizard").get_data(as_text=True)
    assert "function pickAllDomains()" in body
    seg = body.split("function pickAllDomains()", 1)[1].split("\n}\n", 1)[0]
    assert "cb.checked = true" in seg
    assert "saveDomainVisibility()" in seg


def test_clear_picks_fn_unchecks_everything_and_saves(client):
    body = client.get("/wizard").get_data(as_text=True)
    assert "function clearDomainPicks()" in body
    seg = body.split("function clearDomainPicks()", 1)[1].split("\n}\n", 1)[0]
    assert "cb.checked = false" in seg
    assert "saveDomainVisibility()" in seg
