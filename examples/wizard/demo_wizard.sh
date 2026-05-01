#!/usr/bin/env bash
# ============================================================
# Wizard demo — runs the onboarding wizard non-interactively
# from a pre-built session file (Smart Building Operations) and
# walks the artifacts it produces.
#
# Phases:
#   1. Load examples/wizard/smart_building_session.json
#   2. Generate the project skeleton (schema.sql, seed.sql, scope-charter.md, cq-catalog.md)
#   3. Run the toolkit pipeline against the generated DB
#   4. Print where to find the resulting artifacts
#
# Usage:
#   ./examples/wizard/demo_wizard.sh             # run end-to-end
#   ./examples/wizard/demo_wizard.sh --dry-run   # generate files only (skip pipeline)
#   ./examples/wizard/demo_wizard.sh --fresh     # rebuild from scratch (wipes projects/smart_building)
#   ./examples/wizard/demo_wizard.sh --browser   # also start the browser wizard with this session loaded
# ============================================================
set -euo pipefail

DRY_RUN=""
FRESH=""
BROWSER=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN="--dry-run" ;;
    --fresh)   FRESH="1" ;;
    --browser) BROWSER="1" ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

# cd to repo root (this script lives in examples/wizard/)
cd "$(dirname "$0")/../.."

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

SESSION="examples/wizard/smart_building_session.json"
PROJECT="projects/smart_building"

if [[ -n "$FRESH" ]]; then
  step "Cleaning previous run"
  rm -rf "$PROJECT"
fi

step "1/3  Load wizard session"
echo "  session: $SESSION"
echo "  domain:  $(python3 -c "import json; print(json.load(open('$SESSION'))['domain_name'])")"
echo "  entities: $(python3 -c "import json; s=json.load(open('$SESSION')); print(len([e for e in s['entities'] if not e['is_event']]))") business + $(python3 -c "import json; s=json.load(open('$SESSION')); print(len([e for e in s['entities'] if e['is_event']]))") event"
echo "  relationships: $(python3 -c "import json; print(len(json.load(open('$SESSION'))['relationships']))")"
echo "  competency questions: $(python3 -c "import json; print(len(json.load(open('$SESSION'))['cqs']))")"

step "2/3  Generate project skeleton + run pipeline"
# `--from` triggers an interactive confirm before running the pipeline.
# Pipe `y\n` so the demo runs non-interactively.
printf 'y\n' | python3 onboard.py --from "$SESSION" $DRY_RUN

if [[ -n "$BROWSER" ]]; then
  step "3/3  Start browser wizard (Ctrl+C to stop)"
  echo "  Open http://localhost:5000 — the Smart Building session will be available under Templates → load."
  python3 wizard/app.py
  exit 0
fi

step "3/3  Artifacts produced"
cat <<EOF

  Project skeleton:
    $PROJECT/db/schema.sql            ← ontology_metadata-driven schema
    $PROJECT/db/seed.sql              ← annotation rows seeded from your wizard answers
    $PROJECT/docs/scope-charter.md    ← phase 1 charter (auto-generated)
    $PROJECT/docs/cq-catalog.md       ← competency question catalog
    $PROJECT/session.json             ← resumable wizard state

  Generated ontology + reports:
    $PROJECT/output/ontology/enterprise.ttl
    $PROJECT/output/shapes/enterprise-shapes.ttl
    $PROJECT/output/jsonld/enterprise-context.json
    $PROJECT/output/reports/toolkit_report.html

  To resume editing this domain in the wizard:
    python3 onboard.py --from $PROJECT/session.json

  To start over with the browser wizard pre-loaded with this session:
    ./examples/wizard/demo_wizard.sh --fresh --browser

══════════════════════════════════════════════════════════════
EOF
