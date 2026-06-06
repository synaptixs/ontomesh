"""P1.2 — Marketing landing page tests.

Verify the new ``/`` serves the marketing landing, the wizard moved
to ``/wizard``, legacy ``/?step=X`` and ``/index`` bookmarks redirect,
the landing page's a11y baseline holds (skip-link, landmark roles,
heading hierarchy), the brand wordmark is wired into nav and footer,
and the new landing CSS is reachable.
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


# ── Routing ───────────────────────────────────────────────────────────


def test_root_serves_landing_not_wizard(client):
    rv = client.get("/")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Hero headline + tagline are landing-only.
    assert "The ontology mesh" in body
    assert "GraphRAG" in body
    # The wizard's sidebar (with the step-nav) is NOT present.
    assert 'id="step-nav"' not in body
    # Marketing-only sections.
    assert 'class="hero"' in body
    assert 'class="howto"' in body


def test_wizard_route_serves_the_chrome(client):
    rv = client.get("/wizard")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Sidebar step-nav (wizard) IS present.
    assert 'id="step-nav"' in body
    # Marketing hero is NOT in the wizard.
    assert "The ontology mesh" not in body or "step-nav" in body


def test_legacy_step_query_redirects_to_wizard(client):
    rv = client.get("/?step=domain", follow_redirects=False)
    assert rv.status_code == 301
    assert "/wizard" in rv.headers["Location"]
    assert "step=domain" in rv.headers["Location"]


def test_legacy_index_redirects_to_wizard(client):
    rv = client.get("/index", follow_redirects=False)
    assert rv.status_code == 301
    assert "/wizard" in rv.headers["Location"]


# ── Content / sections ────────────────────────────────────────────────


REQUIRED_SECTIONS = [
    'class="hero"',
    'class="trust"',
    'class="cards"',
    'class="howto"',
    'class="snippet"',
    'class="end-cta"',
    'class="footer"',
]


@pytest.mark.parametrize("marker", REQUIRED_SECTIONS)
def test_landing_carries_section(client, marker):
    body = client.get("/").get_data(as_text=True)
    assert marker in body, f"landing missing section {marker}"


def test_landing_has_two_distinct_ctas_to_wizard(client):
    """A marketing landing without a CTA isn't a landing.  We want
    the wizard link visible above the fold (nav + hero) and again
    at the bottom."""
    body = client.get("/").get_data(as_text=True)
    # /wizard appears at least 3 times: nav, hero, end-cta, footer.
    assert body.count('href="/wizard"') >= 3, \
        f"only {body.count('href=\"/wizard\"')} wizard CTAs"


def test_landing_install_snippet_present(client):
    """P1.2.5 grounded these in reality — see test_package_surface.py
    for the deeper assertions.  Smoke test: install instructions and
    a real CLI command are both visible."""
    body = client.get("/").get_data(as_text=True)
    assert "git clone" in body
    assert "pip install -e ." in body
    assert "ontomesh-wizard" in body


# ── A11y baseline ─────────────────────────────────────────────────────


def test_landing_has_skip_link(client):
    body = client.get("/").get_data(as_text=True)
    assert 'class="skip-link"' in body
    assert 'href="#main"' in body


def test_landing_has_main_landmark(client):
    body = client.get("/").get_data(as_text=True)
    assert 'id="main"' in body
    assert "<main" in body


def test_landing_has_single_h1(client):
    """Each marketing page MUST have exactly one h1 — assistive tech
    relies on this for the page outline."""
    body = client.get("/").get_data(as_text=True)
    assert body.count("<h1") == 1


def test_landing_has_aria_labelled_sections(client):
    body = client.get("/").get_data(as_text=True)
    # Every section uses aria-labelledby (skipping <aside>s) so a
    # screen-reader user can hop section-to-section.
    for sec in ("hero-h", "build-h", "how-h", "snip-h", "end-h"):
        assert f'aria-labelledby="{sec}"' in body, \
            f"section {sec!r} not aria-labelledby-wired"


# ── Brand wiring ──────────────────────────────────────────────────────


def test_landing_uses_brand_wordmark_in_nav(client):
    body = client.get("/").get_data(as_text=True)
    assert "brand/ontomesh-wordmark.svg" in body


def test_landing_uses_brand_mark_in_footer(client):
    body = client.get("/").get_data(as_text=True)
    assert "brand/ontomesh-mark.svg" in body


def test_landing_css_reachable(client):
    rv = client.get("/static/css/landing.css")
    assert rv.status_code == 200
    text = rv.get_data(as_text=True)
    # Token usage so re-skins flow through. The landing drives interactive
    # accents through --accent (navy + lime-green uplift); --brand resolves
    # to light ink on the Twilight canvas and is reserved for structure.
    assert "var(--accent)" in text
    assert ".hero" in text
    assert ".card" in text


# ── Help pages keep their back-link consistent ────────────────────────


def test_help_back_link_points_at_wizard(client):
    body = client.get("/help/domain").get_data(as_text=True)
    assert "/wizard?step=domain" in body
    # And the breadcrumb leads with Ontomesh, then Wizard.
    assert ">Ontomesh<" in body
    assert ">Wizard<" in body
