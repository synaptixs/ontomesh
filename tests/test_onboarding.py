"""P1.3 — First-run onboarding tests.

The onboarding modal is JS-rendered, so these tests verify the
*wiring* — that the module is reachable through the Flask static
handler, that the wizard's <head> imports it and exposes
``window.Onboarding``, that the ``init()`` flow calls
``maybeShow``, and that the supporting API endpoints
(``/api/templates``, ``/api/template/<name>``) still respond with
the expected shape.

The modal's interactive behaviour (focus trap, ESC dismiss,
backdrop click) is covered by manual QA — there's no JSDOM here
to assert it.  The wiring tests below catch regressions in the
non-interactive surface.
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


# ── Module reachable ─────────────────────────────────────────────────


def test_onboarding_module_is_reachable_via_static(client):
    rv = client.get("/static/js/components/onboarding.js")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Public surface.
    assert "export class Onboarding" in body
    assert "maybeShow" in body
    assert "showNow"   in body
    assert "reset"     in body


def test_onboarding_module_uses_existing_template_api():
    """The module must call the backend endpoints that already exist —
    don't add a new endpoint we'd then have to wire."""
    src = (ROOT / "wizard" / "static" / "js" / "components"
                / "onboarding.js").read_text()
    assert "/api/templates"   in src
    # The "apply a template" endpoint is /api/template/<name>; the
    # JS builds that path in init(), not here, so we only require
    # one of them is referenced from the module.
    assert "fetch" in src


# ── Wizard <head> wiring ─────────────────────────────────────────────


def test_wizard_head_imports_onboarding(client):
    body = client.get("/wizard").get_data(as_text=True)
    # Module imported with the correct URL helper.
    assert "onboarding.js" in body
    # Exposed on window so devs can force-show / reset.
    assert "window.Onboarding" in body


def test_init_calls_maybe_show(client):
    body = client.get("/wizard").get_data(as_text=True)
    # The init() hook reaches into Onboarding.maybeShow.
    assert "Onboarding.maybeShow" in body
    # Both callbacks must be wired so the user reaches Step 2 on
    # template pick and gets the "starting blank" toast on skip.
    assert "onTemplatePicked" in body
    assert "onSkip"           in body
    assert "/api/template/" in body
    assert "goStep('entities')" in body


def test_landing_does_NOT_load_onboarding(client):
    """The landing page is a marketing surface — the onboarding
    overlay belongs to /wizard, not /."""
    body = client.get("/").get_data(as_text=True)
    assert "onboarding.js" not in body
    assert "Onboarding.maybeShow" not in body


# ── Supporting backend endpoints still respond ────────────────────────


def test_templates_endpoint_lists_industries(client):
    rv = client.get("/api/templates")
    assert rv.status_code == 200
    data = rv.get_json()
    # Both keys are required by the JS shim.
    assert "all" in data
    assert "templates" in data
    # The five canonical built-ins must be in the 'all' list so the
    # onboarding modal can always show them.
    for industry in ("telecom", "healthcare", "finance",
                     "manufacturing", "retail"):
        assert industry in data["all"], \
            f"{industry} missing from /api/templates 'all' list"


def test_template_apply_endpoint_loads_session(client):
    """Picking a card in the onboarding modal POST-loads this URL.
    The endpoint must succeed and return a session-shaped payload."""
    rv = client.get("/api/template/healthcare")
    assert rv.status_code == 200
    data = rv.get_json()
    # Session-shape sanity.
    assert "domain"   in data
    assert "entities" in data
    assert len(data["entities"]) > 0


def test_unknown_template_returns_404(client):
    rv = client.get("/api/template/no-such-template")
    assert rv.status_code == 404


# ── A11y / structure ─────────────────────────────────────────────────


def test_onboarding_module_declares_aria_attributes():
    """The injected modal must carry role='dialog', aria-modal, and
    a labelled heading so assistive tech announces it correctly."""
    src = (ROOT / "wizard" / "static" / "js" / "components"
                / "onboarding.js").read_text()
    assert 'setAttribute("role", "dialog")'       in src
    assert 'setAttribute("aria-modal", "true")'   in src
    assert 'setAttribute("aria-labelledby"'       in src
    # Escape key dismiss + focus trap.
    assert "Escape" in src
    assert "Tab"    in src


def test_wizard_css_carries_onboarding_styles():
    css = (ROOT / "wizard" / "static" / "css" / "wizard.css").read_text()
    for sel in ("#onb-root", ".onb-backdrop", ".onb-modal",
                ".onb-card", ".onb-grid", ".onb-skip"):
        assert sel in css, f"wizard.css missing {sel}"
