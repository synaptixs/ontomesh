"""P1.4 — Project dashboard at /projects.

Verifies the standalone dashboard route renders, carries the four
KPI cards, the filter bar, the project-grid container, the empty
state, and is reachable from both the marketing landing nav and
the wizard.  The backend ``/api/ontologies`` shape it relies on is
also smoke-tested.
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


# ── Route ─────────────────────────────────────────────────────────────


def test_projects_route_returns_200(client):
    rv = client.get("/projects")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Branded surface, not a placeholder.
    assert "Your projects" in body
    assert "Ontomesh" in body


def test_projects_html_has_brand_chrome(client):
    body = client.get("/projects").get_data(as_text=True)
    assert "brand/favicon.svg"          in body
    assert "brand/ontomesh-wordmark.svg" in body
    # Tokens + landing font stack to match the marketing surface.
    assert "css/tokens.css" in body
    assert "Inter+Tight"    in body


# ── KPI strip ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("kpi_id", [
    "kpi-row", "kpi-count", "kpi-latest", "kpi-domains", "kpi-products",
])
def test_kpi_strip_carries_all_four_metrics(client, kpi_id):
    body = client.get("/projects").get_data(as_text=True)
    assert f'id="{kpi_id}"' in body, f"KPI element {kpi_id} missing"


def test_kpi_strip_is_aria_live(client):
    body = client.get("/projects").get_data(as_text=True)
    # The KPI row is announced to AT when projects load.
    seg = body.split('id="kpi-row"', 1)[1].split("</div>", 1)[0]
    assert 'aria-live="polite"' in seg


# ── Filter bar ────────────────────────────────────────────────────────


def test_filter_bar_present(client):
    body = client.get("/projects").get_data(as_text=True)
    assert 'id="filter-input"' in body
    assert 'id="domain-chips"' in body
    # The "All" chip starts active.
    assert 'class="chip active"' in body


# ── Project grid + actions ────────────────────────────────────────────


def test_project_grid_present(client):
    body = client.get("/projects").get_data(as_text=True)
    assert 'id="project-grid"' in body


def test_resume_action_posts_to_load_endpoint(client):
    body = client.get("/projects").get_data(as_text=True)
    # The resume action POSTs to the existing load endpoint with the
    # project's slug, then navigates the user to the wizard.
    assert "/api/ontologies/" in body
    assert "/load" in body
    assert "/wizard?step=domain" in body


def test_delete_action_calls_delete_endpoint(client):
    body = client.get("/projects").get_data(as_text=True)
    assert "function deleteProject" in body
    # Confirm dialog before destructive action.
    seg = body.split("function deleteProject", 1)[1].split("\n}\n", 1)[0]
    assert "confirm(" in seg
    assert "method: \"DELETE\"" in seg \
        or "method:'DELETE'" in seg


# ── Empty state ───────────────────────────────────────────────────────


def test_empty_state_offers_new_project(client):
    body = client.get("/projects").get_data(as_text=True)
    # Two empty states ship in the JS: true-empty and filter-empty.
    assert "No projects yet" in body
    assert "+ New project" in body
    assert "No matches" in body


def test_new_project_button_clears_onboarding_dismiss(client):
    """+ New project must reset the localStorage dismissed flag so
    the first-run onboarding modal pops on /wizard arrival."""
    body = client.get("/projects").get_data(as_text=True)
    assert "function newProjectFromWizard" in body
    seg = body.split("function newProjectFromWizard", 1)[1].split("\n}\n", 1)[0]
    assert "ontomesh.onboarding.dismissed.v1" in seg


# ── Reachable from other surfaces ─────────────────────────────────────


def test_landing_nav_links_to_projects(client):
    """A returning user should be one click away from their work."""
    body = client.get("/").get_data(as_text=True)
    assert 'href="/projects"' in body


def test_projects_nav_links_back_home_and_wizard(client):
    body = client.get("/projects").get_data(as_text=True)
    assert 'href="/wizard"' in body
    assert 'href="/"' in body
    # And to the docs.
    assert 'href="/help"' in body


# ── Backend smoke ─────────────────────────────────────────────────────


def test_ontologies_endpoint_returns_expected_shape(client):
    rv = client.get("/api/ontologies")
    assert rv.status_code == 200
    data = rv.get_json()
    assert "ontologies" in data
    assert isinstance(data["ontologies"], list)
    # If any projects exist, they carry the fields the dashboard reads.
    if data["ontologies"]:
        proj = data["ontologies"][0]
        for k in ("slug", "domain", "product", "label",
                  "created_at", "updated_at"):
            assert k in proj, f"saved ontology missing {k}"


# ── A11y ──────────────────────────────────────────────────────────────


def test_dashboard_has_skip_link_and_main(client):
    body = client.get("/projects").get_data(as_text=True)
    assert 'class="skip-link"' in body
    assert 'href="#main"' in body
    assert '<main id="main"' in body


def test_dashboard_has_single_h1(client):
    body = client.get("/projects").get_data(as_text=True)
    assert body.count("<h1") == 1
