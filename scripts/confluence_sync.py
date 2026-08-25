#!/usr/bin/env python3
"""Publish the repo's documentation to Confluence as a generated mirror.

The repository is the source of truth. Confluence is a rendered copy, and
every page carries a banner saying so — documentation that is editable in two
places drifts, which is precisely the failure this project exists to prevent.

Idempotent: a manifest maps each source file to the page it created, so a
second run *updates* those pages instead of making twenty more.

    python scripts/confluence_sync.py --dry-run          # convert, write nothing
    python scripts/confluence_sync.py --only overview    # one page
    python scripts/confluence_sync.py                    # full sync

Credentials come from .env (CONFLUENCE_BASE_URL / _EMAIL / _API_TOKEN).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "scripts" / "confluence_manifest.json"
SPACE_ID = "3450339332"          # ontomesh
SPACE_KEY = "ontomesh"
REPO_URL = "https://github.com/synaptixs/ontomesh"

# ── Page tree ────────────────────────────────────────────────────────────────
# slug: (title, source, parent-slug or None, optional section-filter)
# A section filter takes only the named "## " section from the source file,
# which is how one long document becomes several readable pages.
TREE: list[dict[str, Any]] = [
    {"slug": "overview",    "title": "1. Overview",             "src": None,               "parent": None},
    {"slug": "what-is", "desc": "The two-sentence version, what it is not, and the one-line argument.",     "title": "What Ontomesh is",        "src": "PROJECT_STATE.md", "parent": "overview",
     "sections": ["What this is"]},
    {"slug": "for-teams", "desc": "Seven problems your team will recognise, and what the toolkit does about each.",   "title": "What it gives an engineering team", "src": "PROJECT_STATE.md", "parent": "overview",
     "sections": ["What this gives an engineering team"]},
    {"slug": "capabilities", "desc": "Modelling, discovery, governance and integration — what is actually in the box.","title": "Capabilities",            "src": "PROJECT_STATE.md", "parent": "overview",
     "sections": ["Capabilities"]},
    {"slug": "limitations", "desc": "What it does not do, stated plainly. Read this before you plan around it.", "title": "Honest limitations",      "src": "PROJECT_STATE.md", "parent": "overview",
     "sections": ["Honest limitations"]},

    {"slug": "start",       "title": "2. Getting started",      "src": None,               "parent": None},
    {"slug": "install", "desc": "pip, Docker, or from source. Five minutes.",     "title": "Install",                 "src": "docs/getting-started/install.md", "parent": "start"},
    {"slug": "quickstart", "desc": "First ontology out of your own database.",  "title": "Quickstart",              "src": "docs/getting-started/quickstart.md", "parent": "start"},
    {"slug": "first-wizard", "desc": "The browser wizard, step by step.","title": "First wizard run",        "src": "docs/getting-started/first-wizard.md", "parent": "start"},

    {"slug": "how",         "title": "3. How it works",         "src": None,               "parent": None},
    {"slug": "pipeline", "desc": "Every `--phase`, in run order, with the flags that matter.",    "title": "Pipeline phases",         "src": "docs/concepts/pipeline.md", "parent": "how"},
    {"slug": "model", "desc": "What the OWL actually contains and how to read it. The core reference.",       "title": "The ontology model",      "src": "docs/concepts/ontology-model.md", "parent": "how"},
    {"slug": "logs", "desc": "How machine learning turns raw logs into entities, relationships and events — and where you decide.",        "title": "Finding the model in your logs (ML)", "src": "PROJECT_STATE.md", "parent": "how",
     "sections": ["Finding the model in your logs"]},
    {"slug": "grounding", "desc": "The four mechanisms that stop an LLM inventing things.",   "title": "Grounding an LLM",        "src": "PROJECT_STATE.md", "parent": "how",
     "sections": ["How the grounding actually works"]},
    {"slug": "drift", "desc": "Detecting when the world moves and the model has not.",       "title": "Drift monitoring",        "src": "docs/concepts/drift.md", "parent": "how"},

    {"slug": "reference",   "title": "4. Reference",            "src": None,               "parent": None},
    {"slug": "artifacts", "desc": "Every generated file and what it is for.",   "title": "Generated artifacts",     "src": "docs/artifacts.md", "parent": "reference"},
    {"slug": "gates", "desc": "The CI ratchet, the quality report, the governance scorecard.",       "title": "Quality gates",           "src": "docs/reference/quality-gates.md", "parent": "reference"},
    {"slug": "search", "desc": "Ontology-grounded search over your data.",      "title": "Reasoning search",        "src": "docs/reference/search.md", "parent": "reference"},
    {"slug": "runtime", "desc": "Connecting the ontology to an LLM at runtime.",     "title": "Runtime layer",           "src": "docs/runtime.md",  "parent": "reference"},
    {"slug": "metadata", "desc": "Steering generation without touching code.",    "title": "Driving generation with metadata", "src": "docs/metadata.md", "parent": "reference"},

    {"slug": "deploy",      "title": "5. Deployment",           "src": "docs/deployment/index.md", "parent": None},
    {"slug": "docker", "desc": "The published image.",      "title": "Docker",                  "src": "docs/deployment/docker.md", "parent": "deploy"},
    {"slug": "compose", "desc": "Single-host stack.",     "title": "Docker Compose",          "src": "docs/deployment/compose.md", "parent": "deploy"},
    {"slug": "postgres", "desc": "Swapping SQLite for Postgres.",    "title": "Postgres backend",        "src": "docs/deployment/postgres.md", "parent": "deploy"},
    {"slug": "production", "desc": "Hardening for real traffic.",  "title": "Production hardening",    "src": "docs/deployment/production.md", "parent": "deploy"},

    {"slug": "project",     "title": "6. Project",              "src": None,               "parent": None},
    {"slug": "roadmap", "desc": "How the current state was reached, phase by phase, with measurements.",     "title": "Roadmap and history",     "src": "ONTOLOGY_ROADMAP.md", "parent": "project"},
    {"slug": "changelog", "desc": "What changed in each release, including breaking changes.",   "title": "Changelog",               "src": "CHANGELOG.md",     "parent": "project"},
]

# Section landing pages get a short intro instead of a source file.
SECTION_INTROS = {
    "overview":  ("Start here. What Ontomesh is, who it is for, what it can do — and, "
                  "just as importantly, what it cannot."),
    "start":     ("Get it installed and produce a first ontology from your own database. "
                  "Budget about fifteen minutes."),
    "how":       ("The mechanics. How the pipeline runs, what the ontology contains, how "
                  "machine learning mines your logs for candidates, and how an LLM is held "
                  "to the result."),
    "reference": ("Look-up material. What each generated file is for, how the quality gates "
                  "work, and the runtime surfaces you can build against."),
    "deploy":    ("Running it somewhere other than your laptop."),
    "project":   ("How the codebase reached its current state, and what changed in each "
                  "release."),
}

_ADMONITION = re.compile(r'^!!!\s+(\w+)(?:\s+"([^"]*)")?\s*$')
_MACRO_MAP = {"note": "note", "info": "info", "tip": "tip", "warning": "warning",
              "danger": "warning", "caution": "warning", "important": "note",
              "example": "info", "abstract": "info"}


def extract_sections(md: str, wanted: list[str]) -> str:
    """Return only the named `## ` sections (and their subsections)."""
    lines = md.splitlines()
    out, capturing = [], False
    for line in lines:
        if line.startswith("## "):
            title = line[3:].strip()
            capturing = any(w.lower() in title.lower() for w in wanted)
            if capturing:
                out.append(line)
            continue
        if line.startswith("# "):        # a new H1 ends any capture
            capturing = False
            continue
        if capturing:
            out.append(line)
    return "\n".join(out).strip()


def preprocess_admonitions(md: str) -> str:
    """Turn mkdocs `!!! type "Title"` blocks into fenced markers.

    Converted after the HTML pass, because the body needs normal Markdown
    rendering first.
    """
    lines, out, i = md.splitlines(), [], 0
    while i < len(lines):
        m = _ADMONITION.match(lines[i])
        if not m:
            out.append(lines[i]); i += 1; continue
        kind = _MACRO_MAP.get(m.group(1).lower(), "info")
        title = m.group(2) or ""
        i += 1
        body = []
        while i < len(lines) and (not lines[i].strip() or lines[i].startswith(("    ", "\t"))):
            body.append(re.sub(r"^(    |\t)", "", lines[i])); i += 1
        while body and not body[-1].strip():
            body.pop()
        out.append(f"<!--ADM:{kind}:{html.escape(title)}-->")
        out.extend(body)
        out.append("<!--/ADM-->")
    return "\n".join(out)


def md_to_storage(md: str) -> str:
    """Markdown → Confluence storage format (XHTML + macros)."""
    import markdown as md_lib
    from bs4 import BeautifulSoup, NavigableString

    md = preprocess_admonitions(md)
    raw = md_lib.markdown(md, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    soup = BeautifulSoup(raw, "html.parser")

    # Code blocks -> code macro, preserving language.
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        text = code.get_text() if code else pre.get_text()
        lang = ""
        if code and code.get("class"):
            for c in code["class"]:
                if c.startswith("language-"):
                    lang = c[len("language-"):]
        macro = soup.new_tag("ac:structured-macro")
        macro["ac:name"] = "code"
        macro["ac:schema-version"] = "1"
        if lang:
            p = soup.new_tag("ac:parameter"); p["ac:name"] = "language"
            p.string = _confluence_lang(lang); macro.append(p)
        body = soup.new_tag("ac:plain-text-body")
        body.string = f"§§CDATA_OPEN§§{text}§§CDATA_CLOSE§§"
        macro.append(body)
        pre.replace_with(macro)

    out = str(soup)

    # Admonition markers -> Confluence macros.
    def _adm(m):
        kind, title = m.group(1), m.group(2)
        t = (f'<ac:parameter ac:name="title">{title}</ac:parameter>' if title else "")
        return (f'<ac:structured-macro ac:name="{kind}" ac:schema-version="1">{t}'
                f'<ac:rich-text-body>')
    out = re.sub(r"<!--ADM:(\w+):([^>]*)-->", _adm, out)
    out = out.replace("<!--/ADM-->", "</ac:rich-text-body></ac:structured-macro>")

    out = out.replace("§§CDATA_OPEN§§", "<![CDATA[").replace("§§CDATA_CLOSE§§", "]]>")
    return out


def _confluence_lang(lang: str) -> str:
    return {"bash": "bash", "sh": "bash", "shell": "bash", "console": "bash",
            "python": "python", "py": "python", "sql": "sql", "json": "json",
            "yaml": "yml", "yml": "yml", "turtle": "none", "ttl": "none",
            "sparql": "sql", "text": "none", "": "none"}.get(lang.lower(), "none")


def banner(src: str | None) -> str:
    """The 'generated, edit in the repo' notice at the top of every page."""
    where = (f' Source: <a href="{REPO_URL}/blob/main/{src}">{src}</a>.' if src else "")
    return (
        '<ac:structured-macro ac:name="info" ac:schema-version="1">'
        '<ac:parameter ac:name="title">Generated page</ac:parameter>'
        '<ac:rich-text-body><p>This page is generated from the '
        f'<a href="{REPO_URL}">synaptixs/ontomesh</a> repository. '
        f'Edits made here are overwritten on the next sync — change the source instead.{where}'
        '</p></ac:rich-text-body></ac:structured-macro>'
    )


# ── Confluence API ───────────────────────────────────────────────────────────
def _cfg() -> tuple[str, str]:
    base = os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/")
    email = os.environ.get("CONFLUENCE_EMAIL", "")
    token = os.environ.get("CONFLUENCE_API_TOKEN", "")
    if not (base and email and token):
        sys.exit("CONFLUENCE_BASE_URL / _EMAIL / _API_TOKEN must be set (see .env)")
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    return base, auth


def api(method: str, path: str, payload: dict | None = None) -> dict:
    base, auth = _cfg()
    url = f"{base}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from None


def create_page(title: str, storage: str, parent_id: str | None) -> dict:
    payload = {"spaceId": SPACE_ID, "status": "current", "title": title,
               "body": {"representation": "storage", "value": storage}}
    if parent_id:
        payload["parentId"] = parent_id
    return api("POST", "/api/v2/pages", payload)


def update_page(page_id: str, title: str, storage: str) -> dict:
    cur = api("GET", f"/api/v2/pages/{page_id}")
    ver = cur.get("version", {}).get("number", 1)
    payload = {"id": page_id, "status": "current", "title": title,
               "body": {"representation": "storage", "value": storage},
               "version": {"number": ver + 1, "message": "Synced from repo"}}
    return api("PUT", f"/api/v2/pages/{page_id}", payload)


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")


def child_table(slug: str) -> str:
    """A landing page should say why you'd open each child, not just name it."""
    rows = []
    for c in TREE:
        if c.get("parent") != slug:
            continue
        desc = html.escape(c.get("desc", ""))
        rows.append(
            "<tr><td><ac:link><ri:page "
            f'ri:content-title="{html.escape(c["title"])}" ri:space-key="{SPACE_KEY}" />'
            f"</ac:link></td><td>{desc}</td></tr>")
    if not rows:
        return ""
    return ("<table><thead><tr><th>Page</th><th>What it covers</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table>")


def build_storage(node: dict) -> str:
    src = node.get("src")
    if src:
        path = ROOT / src
        if not path.exists():
            return banner(src) + f"<p><em>Source not found: {src}</em></p>"
        md = path.read_text(encoding="utf-8")
        if node.get("sections"):
            md = extract_sections(md, node["sections"])
        return banner(src) + md_to_storage(md)
    intro = SECTION_INTROS.get(node["slug"], "")
    return banner(None) + f"<p>{html.escape(intro)}</p>" + child_table(node["slug"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync repo docs to Confluence")
    ap.add_argument("--dry-run", action="store_true", help="convert only; write nothing")
    ap.add_argument("--only", help="sync a single slug")
    ap.add_argument("--show", action="store_true", help="print the storage format")
    ap.add_argument("--relink", action="store_true", help="second pass: rewrite internal links")
    ap.add_argument("--home", action="store_true", help="write the space landing page")
    ap.add_argument("--tidy", action="store_true", help="remove Confluence starter templates")
    ap.add_argument("--diagrams", action="store_true", help="attach and embed SVG diagrams")
    args = ap.parse_args()

    if args.relink:
        return rewrite_links()
    if args.home:
        return sync_home()
    if args.tidy:
        archive_templates(); return 0
    if args.diagrams:
        return sync_diagrams()

    nodes = [n for n in TREE if not args.only or n["slug"] == args.only]
    if not nodes:
        sys.exit(f"no such slug: {args.only}")

    manifest = load_manifest()
    created = updated = 0

    for node in nodes:
        storage = build_storage(node)
        if args.show:
            print(f"\n{'='*70}\n{node['title']}\n{'='*70}\n{storage[:3000]}")
        if args.dry_run:
            src = node.get("src") or "(section landing page)"
            print(f"  {node['slug']:14} {len(storage):>7} chars   {node['title']}  <- {src}")
            continue

        parent_id = manifest.get(node["parent"], {}).get("id") if node.get("parent") else None
        existing = manifest.get(node["slug"], {}).get("id")
        if existing:
            update_page(existing, node["title"], storage)
            manifest[node["slug"]]["title"] = node["title"]
            updated += 1
            print(f"  updated  {node['slug']:14} id={existing}  {node['title']}")
        else:
            res = create_page(node["title"], storage, parent_id)
            manifest[node["slug"]] = {"id": res["id"], "title": node["title"],
                                      "src": node.get("src")}
            created += 1
            print(f"  created  {node['slug']:14} id={res['id']}  {node['title']}")
        save_manifest(manifest)

    if not args.dry_run:
        print(f"\n  {created} created, {updated} updated")
        print(f"  manifest: {MANIFEST.relative_to(ROOT)}")
    return 0



# ── Second pass: internal links ──────────────────────────────────────────────
# Relative Markdown links (`../artifacts.md`) become dead hrefs, because page
# IDs do not exist until the pages are created. This pass runs after the tree
# is built, rewriting any link whose target is a source file we published into
# a real Confluence link, and pointing the rest at GitHub so nothing dangles.

def rewrite_links() -> int:
    import re as _re
    manifest = load_manifest()
    by_src = {v["src"]: (slug, v["id"]) for slug, v in manifest.items() if v.get("src")}
    fixed = touched = 0

    for slug, entry in sorted(manifest.items()):
        src = entry.get("src")
        if not src:
            continue
        page = api("GET", f"/api/v2/pages/{entry['id']}?body-format=storage")
        body = page["body"]["storage"]["value"]
        original = body

        def _sub(m):
            nonlocal fixed
            href, text = m.group(1), m.group(2)
            if href.startswith(("http://", "https://", "#", "mailto:")):
                return m.group(0)
            target = os.path.normpath(os.path.join(os.path.dirname(src), href.split("#")[0]))
            hit = by_src.get(target)
            if hit:
                fixed += 1
                return (f'<ac:link><ri:page ri:content-title="'
                        f'{html.escape(manifest[hit[0]]["title"])}" '
                        f'ri:space-key="{SPACE_KEY}" /><ac:link-body>'
                        f'{text}</ac:link-body></ac:link>')
            fixed += 1
            return f'<a href="{REPO_URL}/blob/main/{target}">{text}</a>'

        body = _re.sub(r'<a href="([^"]+)">(.*?)</a>', _sub, body, flags=_re.S)
        if body != original:
            ver = page["version"]["number"]
            api("PUT", f"/api/v2/pages/{entry['id']}", {
                "id": entry["id"], "status": "current", "title": page["title"],
                "body": {"representation": "storage", "value": body},
                "version": {"number": ver + 1, "message": "Rewrite internal links"}})
            touched += 1
            print(f"  relinked {slug:14} ({fixed} links so far)")
    print(f"\n  {fixed} links rewritten across {touched} pages")
    return 0

SPACE_HOME_ID = "3450339667"

def _pagelink(title: str) -> str:
    return (f'<ac:link><ri:page ri:content-title="{html.escape(title)}" '
            f'ri:space-key="{SPACE_KEY}" /></ac:link>')


def build_home() -> str:
    """The space landing page.

    Whoever opens this space first sees this. It has one job: get a reader to
    the right page in under thirty seconds, and be honest about what the
    project is. Confluence's default boilerplate does neither.
    """
    routes = [
        ("I'm evaluating whether to use this",
         ["What Ontomesh is", "What it gives an engineering team", "Honest limitations"]),
        ("I want to try it",
         ["Install", "Quickstart"]),
        ("I'm building an AI feature on top of it",
         ["Grounding an LLM", "The ontology model", "Reasoning search"]),
        ("I need to understand how it works",
         ["Pipeline phases", "Finding the model in your logs (ML)", "The ontology model"]),
        ("I'm operating it",
         ["Docker", "Production hardening", "Quality gates"]),
    ]
    rows = "".join(
        f"<tr><td><strong>{html.escape(intent)}</strong></td><td>"
        + " &rarr; ".join(_pagelink(t) for t in pages) + "</td></tr>"
        for intent, pages in routes)

    sections = "".join(
        f"<tr><td>{_pagelink(n['title'])}</td>"
        f"<td>{html.escape(SECTION_INTROS.get(n['slug'], ''))}</td></tr>"
        for n in TREE if n.get("parent") is None)

    return (
        banner(None)
        + "<h2>What this is</h2>"
        "<p>Ontomesh turns the systems you already run &mdash; a database schema, "
        "application logs &mdash; into a formal model of what your data means, and then "
        "uses that model to control what an LLM is allowed to say about it.</p>"
        '<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body>'
        "<p>An LLM pointed at a database can say anything. An LLM pointed at a database "
        "<em>through an ontology</em> can only say things the ontology has words for, "
        "about data it is cleared to read &mdash; and it has to show its sources.</p>"
        "</ac:rich-text-body></ac:structured-macro>"
        "<h2>Where to start</h2>"
        "<p>Pick the row that matches why you are here.</p>"
        "<table><thead><tr><th>If you are&hellip;</th><th>Read, in order</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<h2>All sections</h2>"
        "<table><thead><tr><th>Section</th><th>What it covers</th></tr></thead>"
        f"<tbody>{sections}</tbody></table>"
        "<h2>Source</h2>"
        f'<p>Everything here is generated from <a href="{REPO_URL}">synaptixs/ontomesh</a>. '
        "The package is published to PyPI as <code>ontoforge</code>. To change a page, "
        "change the source file it names and re-run the sync.</p>"
    )


def sync_home() -> int:
    page = api("GET", f"/api/v2/pages/{SPACE_HOME_ID}?body-format=storage")
    api("PUT", f"/api/v2/pages/{SPACE_HOME_ID}", {
        "id": SPACE_HOME_ID, "status": "current", "title": page["title"],
        "body": {"representation": "storage", "value": build_home()},
        "version": {"number": page["version"]["number"] + 1,
                    "message": "Space home: routing and overview"}})
    print(f"  home page updated (id={SPACE_HOME_ID})")
    return 0


def archive_templates() -> int:
    """Remove the two starter templates Confluence creates with a new space."""
    removed = 0
    for pid, name in (("3450339681", "Template - How-to guide"),
                      ("3450339694", "Template - Troubleshooting article")):
        try:
            api("DELETE", f"/api/v2/pages/{pid}")
            print(f"  removed  {name}")
            removed += 1
        except RuntimeError as e:
            print(f"  skipped  {name} ({e})")
    return removed


# ── Diagrams ─────────────────────────────────────────────────────────────────
# Confluence renders an attached SVG through <ac:image>. Upload is the v1 API
# (v2 has no multipart endpoint), so this is the one place we drop to /rest/api.
# Attachments are keyed by filename, so re-uploading replaces rather than
# duplicates — the sync stays idempotent.

DIAGRAMS = {
    "what-is":  ("stack.svg",      "Where Ontomesh sits in a stack"),
    "pipeline": ("pipeline.svg",   "From your systems to a governed model"),
    "grounding":("grounding.svg",  "Four gates between a question and an answer"),
    "logs":     ("log-mining.svg", "How logs become ontology candidates"),
}
DIAGRAM_DIR = ROOT / "docs" / "diagrams"


def upload_attachment(page_id: str, path: Path) -> bool:
    """Attach a file, replacing any existing attachment of the same name."""
    import mimetypes, uuid
    base, auth = _cfg()
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".svg":
        mime = "image/svg+xml"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="minorEdit"\r\n\r\ntrue\r\n',
        f"--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        f"{base}/rest/api/content/{page_id}/child/attachment", data=body, method="PUT")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("X-Atlassian-Token", "no-check")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=60):
            return True
    except urllib.error.HTTPError as e:
        print(f"    attach failed: {e.code} {e.read().decode()[:160]}")
        return False


def image_macro(filename: str, alt: str) -> str:
    return (f'<p><ac:image ac:align="center" ac:layout="center" ac:alt="{html.escape(alt)}">'
            f'<ri:attachment ri:filename="{filename}" /></ac:image></p>'
            f'<p style="text-align:center"><em>{html.escape(alt)}</em></p>')


def sync_diagrams() -> int:
    """Attach each diagram and place it directly under its page's banner."""
    manifest = load_manifest()
    done = 0
    for slug, (fname, alt) in DIAGRAMS.items():
        entry = manifest.get(slug)
        src = DIAGRAM_DIR / fname
        if not entry or not src.exists():
            print(f"  skipped  {slug} ({'no page' if not entry else 'no ' + fname})")
            continue
        if not upload_attachment(entry["id"], src):
            continue
        page = api("GET", f"/api/v2/pages/{entry['id']}?body-format=storage")
        body = page["body"]["storage"]["value"]
        macro = image_macro(fname, alt)
        if f'ri:filename="{fname}"' in body:
            done += 1
            print(f"  ok       {slug:10} {fname} (already embedded)")
            continue
        # Insert after the generated-page banner so the diagram leads the content.
        marker = "</ac:structured-macro>"
        idx = body.find(marker)
        body = (body[: idx + len(marker)] + macro + body[idx + len(marker):]
                if idx != -1 else macro + body)
        api("PUT", f"/api/v2/pages/{entry['id']}", {
            "id": entry["id"], "status": "current", "title": page["title"],
            "body": {"representation": "storage", "value": body},
            "version": {"number": page["version"]["number"] + 1,
                        "message": f"Embed {fname}"}})
        done += 1
        print(f"  embedded {slug:10} {fname}")
    print(f"\n  {done} diagram(s) live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
