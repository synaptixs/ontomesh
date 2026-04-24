#!/usr/bin/env bash
# ============================================================
# 5G-NF First-Contact Demo — one-command runner
#
# Phases:
#   1. Build db/demo_5g.db from db/demo_5g.sql + db/demo_5g_seed.sql
#   2. Generate the ontology into output/demo-5g/ via toolkit.py
#   3. Baseline LLM calls (no ontology)
#   4. Grounded LLM calls (RuntimeClient flavor=fiveg)
#   5. Build output/demo-5g/{comparison,executive}.html + comparison.csv
#
# Usage:
#   ./demo_5g.sh            # auto-detect API keys; fall back to illustrative
#   ./demo_5g.sh --live     # require API keys; fail loudly if missing
#   ./demo_5g.sh --fresh    # wipe output/demo-5g/ and db/demo_5g.db first
#   ./demo_5g.sh --open     # also open the executive view in a browser
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
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")"

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

if [[ -n "$FRESH" ]]; then
  step "Cleaning previous 5G demo run"
  rm -rf output/demo-5g db/demo_5g.db
fi

step "1/5  Build 5G demo database"
mkdir -p db
rm -f db/demo_5g.db
sqlite3 db/demo_5g.db < db/demo_5g.sql
sqlite3 db/demo_5g.db < db/demo_5g_seed.sql
echo "  db/demo_5g.db ready ($(sqlite3 db/demo_5g.db "SELECT COUNT(*) FROM nf_instance") NFs, $(sqlite3 db/demo_5g.db "SELECT COUNT(*) FROM pdu_session") PDU sessions, $(sqlite3 db/demo_5g.db "SELECT COUNT(*) FROM nf_event") events)"

step "2/5  Generate the ontology"
python3 toolkit.py --db db/demo_5g.db --out output/demo-5g 2>&1 | tail -8

step "3/5  Baseline LLM calls (no ontology)"
python3 scripts/demo_5g.py baseline $LIVE

step "4/5  Ontology-grounded LLM calls"
python3 scripts/demo_5g.py grounded $LIVE

step "5/5  Build comparison reports"
python3 scripts/demo_5g.py report

cat <<EOF

══════════════════════════════════════════════════════════════
  5G Demo complete.

  Engineering view (full 8×2×2 matrix + ontology map):
    open output/demo-5g/comparison.html

  Executive view (one-page, 3 examples):
    open output/demo-5g/executive.html

  Toolkit pipeline report:
    open output/demo-5g/reports/toolkit_report.html

  Raw per-call outputs:
    ls output/demo-5g/cache/

══════════════════════════════════════════════════════════════
EOF

if [[ -n "$OPEN" ]]; then
  if command -v open >/dev/null 2>&1; then
    open output/demo-5g/executive.html
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open output/demo-5g/executive.html
  fi
fi
