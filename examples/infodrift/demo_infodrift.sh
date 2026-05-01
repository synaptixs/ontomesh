#!/usr/bin/env bash
# ============================================================
# infodrift × ontology-toolkit integration demo — runner
#
# Phases:
#   1. Build db/demo.db (re-uses retail seed)
#   2. Run toolkit.py → output/demo/ (ontology + shapes + JSON-LD context)
#   3. Run examples/infodrift/scripts/demo_infodrift.py
#      - OWL-driven entity discovery
#      - SHACL gate
#      - drift_monitor windows: stable + Black Friday surge
#      - JSON-LD/PROV-O enrichment → output/infodrift/observations.jsonl
#      - OWL propagation
#
# Usage:
#   ./examples/infodrift/demo_infodrift.sh           # idempotent
#   ./examples/infodrift/demo_infodrift.sh --fresh   # wipe output/demo/ + output/infodrift/
# ============================================================
set -euo pipefail

FRESH=""
for a in "$@"; do
  case "$a" in
    --fresh) FRESH="1" ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

# cd to repo root (this script lives in examples/infodrift/)
cd "$(dirname "$0")/../.."

step() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

if [[ -n "$FRESH" ]]; then
  step "Cleaning previous run"
  rm -rf output/demo db/demo.db output/infodrift
fi

if [[ ! -f db/demo.db ]]; then
  step "1/3  Build retail demo database"
  mkdir -p db
  sqlite3 db/demo.db < db/demo.sql
  sqlite3 db/demo.db < db/demo_seed.sql
fi

if [[ ! -f output/demo/ontology/enterprise.ttl ]]; then
  step "2/3  Generate the ontology (toolkit.py)"
  python3 toolkit.py --db db/demo.db --out output/demo 2>&1 | tail -8
fi

step "3/3  Run infodrift integration demo"
python3 examples/infodrift/scripts/demo_infodrift.py

cat <<EOF

══════════════════════════════════════════════════════════════
  infodrift demo complete.

  Observation store (JSON-LD, append-only):
    cat output/infodrift/observations.jsonl

  Source ontology (drove entity discovery):
    output/demo/ontology/enterprise.ttl

  SHACL shapes (gated production frames):
    output/demo/shapes/enterprise-shapes.ttl

══════════════════════════════════════════════════════════════
EOF
