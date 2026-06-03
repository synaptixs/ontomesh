"""P1.5 — Empty-state polish + live SSE pill tests.

Verifies:
1.  The reusable ``renderEmptyState`` helper is defined and used by
    the three earliest panels (Entities / Events / Relationships).
2.  Each empty-state carries a primary CTA and at least one
    supporting action so a brand-new user has a clear next step.
3.  The sidebar footer carries the live SSE pill, wired to
    ``window.LiveBus``'s state-change callback so it auto-updates
    when P0.3's SSE stream connects / drops.
4.  CSS for both .empty-state and .live-pill is in wizard.css.
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


# ── renderEmptyState helper + call-sites ──────────────────────────────


def test_render_empty_state_helper_defined(client):
    body = client.get("/wizard").get_data(as_text=True)
    assert "function renderEmptyState(" in body
    # The helper accepts { icon, title, desc, actions }.
    assert "icon, title, desc, actions" in body
    # And renders the canonical empty-state shape.
    assert 'class="empty-state"' in body
    assert 'class="empty-state-icon"' in body
    assert 'class="empty-state-actions"' in body


@pytest.mark.parametrize("panel,icon_const,primary_action", [
    ("entities",      "ENTITY_ICON", "openEntityModal()"),
    ("events",        "EVENT_ICON",  "openEventModal()"),
    ("relationships", "REL_ICON",    "addRelationship()"),
])
def test_each_panel_uses_empty_state(client, panel, icon_const, primary_action):
    body = client.get("/wizard").get_data(as_text=True)
    # The icon constant is used (proves panel-specific empty state).
    assert icon_const in body, f"{panel} missing {icon_const}"
    # And the panel's primary action is wired into the empty state.
    assert primary_action in body, \
        f"{panel} empty state missing primary action {primary_action}"


def test_bare_no_x_yet_strings_removed(client):
    """The three sites we upgraded MUST no longer emit the bare
    "No X yet" string in their innerHTML — that's the PoC tell we
    just fixed."""
    body = client.get("/wizard").get_data(as_text=True)
    # The strings should no longer appear as inline innerHTML literals.
    assert "'<div style=\"color:var(--muted);font-size:13px;" \
           "padding:8px 0\">No entities yet" not in body
    assert "No events yet.</div>"        not in body
    assert "No relationships yet.</div>" not in body


def test_entities_empty_state_offers_three_paths(client):
    """Add entity / Import schema / Browse templates — three ways
    in, one of which calls the P1.3 onboarding modal."""
    body = client.get("/wizard").get_data(as_text=True)
    # Find the entities empty-state block.
    seg = body.split("ENTITY_ICON,", 1)[1].split("});", 1)[0]
    assert "openEntityModal()"       in seg
    assert "im-drop"                 in seg          # import scroll
    assert "Onboarding.showNow"      in seg          # template picker


# ── Live SSE pill ─────────────────────────────────────────────────────


def test_sidebar_footer_carries_live_pill(client):
    body = client.get("/wizard").get_data(as_text=True)
    assert 'id="live-pill"' in body
    # ARIA wiring so screen readers announce state changes.
    assert 'role="status"' in body
    assert 'aria-live="polite"' in body
    # Initial state attribute and the three sub-elements.
    assert 'data-state="idle"' in body
    assert 'class="dot"' in body
    assert 'class="label"' in body
    assert 'class="stat"' in body


def test_live_pill_wired_to_live_bus(client):
    body = client.get("/wizard").get_data(as_text=True)
    # State-change callback updates the pill.
    assert "live.onStateChange(updateLivePill)" in body
    # All four event kinds bump the event counter.
    assert "'hello'" in body and "'metric'" in body
    assert "'drift'" in body and "'status'" in body


# ── CSS surface ───────────────────────────────────────────────────────


@pytest.mark.parametrize("selector", [
    ".empty-state",
    ".empty-state-icon",
    ".empty-state-actions",
    ".live-pill",
    ".live-pill .dot",
    '.live-pill[data-state="open"]',
])
def test_wizard_css_carries_selector(selector):
    css = (ROOT / "wizard" / "static" / "css" / "wizard.css").read_text()
    assert selector in css, f"wizard.css missing {selector}"
