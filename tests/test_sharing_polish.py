"""P2.6 — Sharing-polish lint tests.

Static checks on the four artifacts that make tester onboarding +
feedback smoother:

- .github/ISSUE_TEMPLATE/tester-feedback.yml (form-based issue)
- .github/ISSUE_TEMPLATE/config.yml (issue picker config)
- CHANGELOG.md (Keep-a-Changelog format)
- deploy/Caddyfile.with-auth.example (shared-instance recipe)

Plus the README link to the issue form + CHANGELOG.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TESTER_FORM    = ROOT / ".github" / "ISSUE_TEMPLATE" / "tester-feedback.yml"
ISSUE_CONFIG   = ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
CHANGELOG      = ROOT / "CHANGELOG.md"
CADDY_AUTH     = ROOT / "deploy" / "Caddyfile.with-auth.example"
README         = ROOT / "README.md"

yaml = pytest.importorskip("yaml")


# ── Tester-feedback issue form ────────────────────────────────────────


@pytest.fixture(scope="module")
def form():
    assert TESTER_FORM.exists(), "tester-feedback.yml missing"
    return yaml.safe_load(TESTER_FORM.read_text())


def test_form_has_required_metadata(form):
    for key in ("name", "description", "title", "labels", "body"):
        assert key in form, f"issue form missing {key}"
    # The auto-applied label is what the README links to.
    assert "tester-feedback" in form["labels"]


def test_form_kind_dropdown_offers_bug_friction_idea(form):
    body = form["body"]
    kinds = [item for item in body if item.get("id") == "kind"]
    assert kinds, "no 'kind' field"
    options = kinds[0]["attributes"]["options"]
    # The three primary kinds, plus docs.
    haystack = " ".join(options).lower()
    for needle in ("bug", "friction", "idea", "docs"):
        assert needle in haystack, f"kind dropdown missing {needle!r}"


def test_form_kind_and_summary_are_required(form):
    body = form["body"]
    required_ids = {item["id"] for item in body
                    if item.get("id") and item.get("validations", {}).get("required")}
    # Only kind + summary are required; everything else is optional.
    assert "kind"    in required_ids
    assert "summary" in required_ids
    # Logs and extra are optional — verify a couple stay optional so
    # we don't accidentally make the form heavy.
    for k in ("logs", "extra"):
        assert k not in required_ids, f"{k} should not be required"


def test_form_collects_environment_context(form):
    """The triage-most-useful fields all present: image tag, platform,
    browser, logs."""
    body = form["body"]
    ids = {item["id"] for item in body if item.get("id")}
    for needed in ("image-tag", "platform", "browser", "logs"):
        assert needed in ids, f"form missing {needed!r} context field"


def test_form_has_privacy_check(form):
    """We're internal — but a checkbox catches the obvious mistakes
    (paste-customer-data-into-an-issue) before they land."""
    body = form["body"]
    privacy = [item for item in body if item.get("id") == "privacy"]
    assert privacy, "no privacy-check"
    # It must be required (a checkbox `required: true` enforces tick).
    opts = privacy[0]["attributes"]["options"]
    assert any(o.get("required") for o in opts), \
        "privacy check option must be required"


# ── Issue picker config ──────────────────────────────────────────────


def test_issue_config_exists():
    assert ISSUE_CONFIG.exists()
    data = yaml.safe_load(ISSUE_CONFIG.read_text())
    # Blank issues stay enabled — sometimes feedback doesn't fit the form.
    assert data.get("blank_issues_enabled") is True


# ── CHANGELOG ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def changelog_text() -> str:
    assert CHANGELOG.exists(), "CHANGELOG.md missing"
    return CHANGELOG.read_text()


def test_changelog_keep_a_changelog_format(changelog_text):
    """Title + standard intro line."""
    assert changelog_text.startswith("# Changelog")
    assert "Keep a Changelog" in changelog_text
    assert "Semantic Versioning" in changelog_text


def test_changelog_has_current_version_section(changelog_text):
    """The current version must have its own section so a tester
    landing on this file sees what just shipped."""
    assert "## [3.6.0-dev]" in changelog_text
    # And it dates the release.
    m = re.search(r"## \[3\.6\.0-dev\] — (\d{4}-\d{2}-\d{2})", changelog_text)
    assert m, "3.6.0-dev section missing or undated"


def test_changelog_covers_p2_phases(changelog_text):
    """Every P2 phase should appear by name so the audit trail is
    direct."""
    for phase in ("P2.1", "P2.2", "P2.3", "P2.4", "P2.5", "P2.6"):
        assert phase in changelog_text, f"CHANGELOG missing {phase}"


def test_changelog_covers_p1_and_p0(changelog_text):
    """The product-surface and UI-polish lines, named by phase."""
    for phase in ("P0.1", "P0.4", "P1.1", "P1.5", "P1.5.2"):
        assert phase in changelog_text, f"CHANGELOG missing {phase}"


def test_changelog_covers_tier_releases(changelog_text):
    """Tier 1 / 2 / 3 releases each get their own section linking
    back to the foundational v1.5."""
    for section in ("## [3.3.0]", "## [3.2.0]", "## [3.1.0]",
                    "## [3.0.0]", "## [1.5]"):
        assert section in changelog_text, f"CHANGELOG missing {section}"


def test_changelog_links_compare_urls(changelog_text):
    """The Keep-a-Changelog footer compare-link block lets readers
    jump to the GitHub diff for each version."""
    assert "[3.6.0-dev]:" in changelog_text
    assert "github.com/nrohilla-fibonacci/ontology/compare/" in changelog_text


# ── Basic-auth Caddyfile example ─────────────────────────────────────


@pytest.fixture(scope="module")
def caddy_text() -> str:
    assert CADDY_AUTH.exists(), "Caddyfile.with-auth.example missing"
    return CADDY_AUTH.read_text()


def test_caddy_auth_uses_basicauth_directive(caddy_text):
    assert "basicauth" in caddy_text


def test_caddy_auth_warns_about_internal_port_exposure(caddy_text):
    """The most-common production-deployment mistake when adding
    basicauth: leaving port 5051 still mapped to the host so anyone
    can bypass Caddy and hit the wizard directly.  The file MUST
    call this out."""
    text = caddy_text.lower()
    assert "bypass" in text or "host port" in text or "ports:" in text


def test_caddy_auth_keeps_sse_timeouts(caddy_text):
    """Forgetting to carry over the 24h read_timeout from the
    regular Caddyfile is a common copy-paste mistake — assert it
    stayed."""
    assert "read_timeout" in caddy_text
    assert "24h" in caddy_text


def test_caddy_auth_keeps_security_headers(caddy_text):
    for header in (
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
    ):
        assert header in caddy_text


def test_caddy_auth_documents_hash_generation(caddy_text):
    """Tester won't know how to generate the bcrypt hash unless we
    say.  The header comment shows the `caddy hash-password` invocation."""
    assert "caddy hash-password" in caddy_text


# ── README wiring ────────────────────────────────────────────────────


def test_readme_links_issue_form_template():
    """The README's Feedback section must deep-link to the
    new-issue page with the template= query string."""
    text = README.read_text()
    assert "issues/new?template=tester-feedback.yml" in text


def test_readme_links_changelog():
    text = README.read_text()
    assert "CHANGELOG.md" in text
