#!/usr/bin/env bash
# ============================================================
# First-Contact Demo — one-command runner
#
# Phases:
#   1. Build db/demo.db from db/demo.sql + db/demo_seed.sql
#   2. Generate the ontology into output/demo/ via toolkit.py
#   3. Call Anthropic + OpenAI without the ontology  (baseline)
#   4. Call Anthropic + OpenAI via RuntimeClient     (grounded)
#   5. Build output/demo/comparison.html + executive.html
#
# Usage:
#   ./demo.sh            # auto-detect API keys; falls back to illustrative answers
#   ./demo.sh --live     # require API keys; fail loudly if missing
#   ./demo.sh --fresh    # rebuild everything from scratch (wipes output/demo/cache/)
#   ./demo.sh --open     # also open executive.html in the default browser
# ============================================================
set -euo pipefail

LIVE=""
FRESH=""
OPEN=""
for a in "$@"; do
  case "$a" in
    --live)  LIVE="--live" ;;
    --fresh) FRESH="1" ;;
    --open)  OPEN="1" ;;
    -h|--help)
      sed -n '2,20p' "$0"; exit 0 ;;
    *)
      echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")"

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

if [[ -n "$FRESH" ]]; then
  step "Cleaning previous demo run"
  rm -rf output/demo db/demo.db
fi

step "1/5  Build demo database"
mkdir -p db
rm -f db/demo.db
sqlite3 db/demo.db < db/demo.sql
sqlite3 db/demo.db < db/demo_seed.sql
echo "  db/demo.db ready ($(sqlite3 db/demo.db "SELECT COUNT(*) FROM orders") orders, $(sqlite3 db/demo.db "SELECT COUNT(*) FROM order_events") events)"

step "2/5  Generate the ontology"
python3 toolkit.py --db db/demo.db --out output/demo 2>&1 | tail -6

step "3/5  Baseline LLM calls (no ontology)"
python3 scripts/demo_baseline.py $LIVE

step "4/5  Ontology-grounded LLM calls"
python3 scripts/demo_grounded.py $LIVE

step "5/5  Build comparison reports"
python3 scripts/demo_report.py

cat <<EOF

══════════════════════════════════════════════════════════════
  Demo complete.

  Engineering view (full 8×2×2 matrix):
    open output/demo/comparison.html

  Executive view (one-page, 3 examples):
    open output/demo/executive.html

  Toolkit pipeline report:
    open output/demo/reports/toolkit_report.html

  Raw per-call outputs:
    ls output/demo/cache/

══════════════════════════════════════════════════════════════
EOF

if [[ -n "$OPEN" ]]; then
  if command -v open >/dev/null 2>&1; then
    open output/demo/executive.html
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open output/demo/executive.html
  fi
fi
