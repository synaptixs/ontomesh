"""P1.1 — Brand identity tests.

Verify the Ontomesh brand assets are present, reachable through the
Flask static handler, wired into every chrome HTML page, surfaced in
the meta tags scrapers read (favicon + OG + Twitter), and that error
pages render with the brand kit.
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


# ── Assets exist on disk ───────────────────────────────────────────────


BRAND_DIR = ROOT / "wizard" / "static" / "brand"

REQUIRED_ASSETS = [
    "favicon.svg",
    "ontomesh-mark.svg",
    "ontomesh-wordmark.svg",
    "ontomesh-wordmark-dark.svg",
    "og-card.svg",
    "twitter-card.svg",
]


@pytest.mark.parametrize("name", REQUIRED_ASSETS)
def test_brand_asset_file_exists(name):
    path = BRAND_DIR / name
    assert path.exists(), f"missing brand asset: {name}"
    assert path.stat().st_size > 200, f"{name} suspiciously small"


@pytest.mark.parametrize("name", REQUIRED_ASSETS)
def test_brand_asset_is_valid_svg(name):
    text = (BRAND_DIR / name).read_text()
    assert text.lstrip().startswith("<svg") or "<svg" in text[:200], \
        f"{name} doesn't look like an SVG"
    assert 'xmlns="http://www.w3.org/2000/svg"' in text
    # Brand colour palette — every asset uses at least one of the
    # canonical brand colours so re-skins are easy to grep for.
    assert any(c in text for c in ("#4f46e5", "#818cf8", "#06b6d4", "#22d3ee", "#0a0a0a")), \
        f"{name} doesn't reference a brand colour"


# ── Tokens ────────────────────────────────────────────────────────────


def test_tokens_css_defines_brand_layer():
    tokens = (ROOT / "wizard" / "static" / "css" / "tokens.css").read_text()
    # All three themes (light / dark / mono) declare the brand layer.
    for token in ("--brand:", "--brand-deep:", "--brand-mesh:",
                  "--brand-bg-soft:", "--on-brand:"):
        assert tokens.count(token) >= 3, \
            f"{token} not declared across all three themes"


# ── pyproject ─────────────────────────────────────────────────────────


def test_pyproject_renamed_to_ontomesh():
    py = (ROOT / "pyproject.toml").read_text()
    assert 'name = "ontomesh"' in py
    assert 'version = "3.6.0-dev"' in py


# ── Flask wiring ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.mark.parametrize("name", REQUIRED_ASSETS)
def test_brand_asset_served_by_flask(client, name):
    rv = client.get(f"/static/brand/{name}")
    assert rv.status_code == 200, f"{name} -> {rv.status_code}"
    assert rv.content_type.startswith("image/svg") or \
           rv.content_type.startswith("application/octet-stream"), \
        f"{name} content-type: {rv.content_type}"


def test_index_has_brand_wired_into_head(client):
    body = client.get("/").get_data(as_text=True)
    # Title rebranded.
    assert "<title>Ontomesh" in body
    # Favicon link.
    assert "brand/favicon.svg" in body
    # OG + Twitter cards.
    assert "og:title" in body
    assert "Ontomesh" in body
    assert "og:image" in body and "brand/og-card.svg" in body
    assert "twitter:card" in body
    assert "twitter:image" in body and "brand/twitter-card.svg" in body
    # Sidebar wordmark, not the old "Ontology Toolkit" string.
    assert "ontomesh-wordmark.svg" in body
    assert "Ontology Toolkit" not in body
    assert "Ontology Studio · v3.0" not in body


def test_phase_help_pages_carry_brand(client):
    body = client.get("/help/domain").get_data(as_text=True)
    assert "Ontomesh Help" in body
    assert "brand/favicon.svg" in body


# ── Error pages ────────────────────────────────────────────────────────


def test_404_page_is_branded(client):
    rv = client.get("/no-such-route")
    assert rv.status_code == 404
    body = rv.get_data(as_text=True)
    assert "Ontomesh" in body
    assert "Page not found" in body
    assert "brand/ontomesh-mark.svg" in body
    assert "Back to Ontomesh" in body
