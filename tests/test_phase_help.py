"""P0.4 — Per-phase help page tests.

Verify every phase declared in ``wizard/help_content.py`` has the
required shape, every slug renders 200 through the Flask route, the
prev/next chain is internally consistent, and unknown slugs 404.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "src"))

flask = pytest.importorskip("flask")

from help_content import HELP_PAGES, all_slugs, get_help            # noqa: E402


REQUIRED = {
    "slug", "step_num", "title", "tagline",
    "what", "why", "capabilities", "workflow", "tips",
}


# ── Content shape ─────────────────────────────────────────────────────


def test_all_pages_have_required_fields():
    for slug, page in HELP_PAGES.items():
        missing = REQUIRED - set(page.keys())
        assert not missing, f"{slug} missing fields: {missing}"
        assert page["slug"] == slug
        assert isinstance(page["title"], str) and page["title"]
        assert isinstance(page["tagline"], str) and page["tagline"]
        assert len(page["what"]) > 80, f"{slug} 'what' too short"
        assert len(page["why"])  > 80, f"{slug} 'why' too short"
        assert len(page["capabilities"]) >= 3
        assert len(page["workflow"])     >= 3
        assert len(page["tips"])         >= 2


def test_capability_and_workflow_entries_are_pairs():
    for slug, page in HELP_PAGES.items():
        for item in page["capabilities"]:
            assert len(item) == 2 and all(isinstance(s, str) for s in item)
        for item in page["workflow"]:
            assert len(item) == 2 and all(isinstance(s, str) for s in item)


# ── Prev / next chain ─────────────────────────────────────────────────


def test_prev_next_chain_is_internally_consistent():
    """If page A.next = B, then B.prev should point back to A."""
    for slug, page in HELP_PAGES.items():
        nxt = page.get("next")
        if nxt is None:
            continue
        target_slug = nxt[0]
        # 'log-discovery' is a permitted off-list neighbour because
        # its help page predates this dict.
        if target_slug == "log-discovery":
            continue
        target = get_help(target_slug)
        assert target is not None, \
            f"{slug}.next points at unknown slug {target_slug}"
        prev = target.get("prev")
        assert prev is not None and prev[0] == slug, \
            f"{target_slug}.prev should be {slug} but is {prev}"


def test_first_page_has_no_prev_and_last_has_no_next():
    slugs = all_slugs()
    assert HELP_PAGES[slugs[0]]["prev"] is None
    assert HELP_PAGES[slugs[-1]]["next"] is None


# ── Flask route ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """A Flask test client for the wizard app."""
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_every_slug_renders_200(client):
    for slug in all_slugs():
        rv = client.get(f"/help/{slug}")
        assert rv.status_code == 200, f"{slug} -> {rv.status_code}"
        body = rv.get_data(as_text=True)
        # Title surfaces in the rendered page (Jinja escapes & → &amp;).
        title_escaped = HELP_PAGES[slug]["title"].replace("&", "&amp;")
        assert title_escaped in body
        # All four required section headings present.
        for heading in (
            "What this phase does", "Why it matters",
            "Key capabilities", "Workflow",
        ):
            assert heading in body, f"{slug} missing section {heading!r}"


def test_log_discovery_help_alias_works(client):
    """/help/log-discovery should hand off to the bespoke page."""
    rv = client.get("/help/log-discovery")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Log Discovery" in body


def test_unknown_slug_returns_404(client):
    rv = client.get("/help/no-such-phase")
    assert rv.status_code == 404


def test_help_index_redirects_to_first_phase(client):
    rv = client.get("/help")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # The first phase is "domain".
    assert HELP_PAGES["domain"]["title"] in body


def test_help_pages_link_back_to_wizard(client):
    """The 'Back to wizard' link sends the user to the right step."""
    rv = client.get("/help/entities")
    body = rv.get_data(as_text=True)
    # P1.2 moved the wizard from / to /wizard; the back-link follows.
    assert "/wizard?step=entities" in body


# ── Cross-link from wizard ─────────────────────────────────────────────


def test_index_html_has_help_pill_for_every_phase():
    """Every phase declared in HELP_PAGES must have a help-pill link
    in the main wizard chrome so users can actually reach the page."""
    index_html = (ROOT / "wizard" / "templates" / "index.html").read_text()
    for slug in all_slugs():
        href = f'/help/{slug}"'
        assert href in index_html, f"index.html missing help link for {slug}"
