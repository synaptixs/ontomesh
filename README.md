# Ontology Engineering Toolkit — v3.0

**Domain-agnostic · Phase 3 complete · Scale & Community edition**

A complete end-to-end implementation of the [Domain-Agnostic Ontology Engineering Framework v1.1](docs/framework-whitepaper.md). Takes a relational database schema and produces a production-ready OWL 2 ontology, SHACL validation shapes, JSON-LD agent payloads, SKOS vocabulary, and a scored governance report — for any domain, any industry, any major relational database.

> **First time here?** Read [docs/integrate.md](docs/integrate.md) — the 5-minute integration recipe. This README is just the landing page.

---

## Get started in 5 minutes

```bash
# Clone + minimum dependencies (~50 MB, no compile, no API keys)
git clone https://github.com/nrohilla-fibonacci/ontology.git
cd ontology
pip install -r requirements-core.txt

# Run the full pipeline against the bundled SQLite demo DB
python3 toolkit.py --db db/demo.db --out output/demo

# Open the report
open output/demo/reports/toolkit_report.html
```

That's the whole loop. You now have a working OWL ontology, SHACL shapes, JSON-LD context, and a governance scorecard under `output/demo/`.

To point at your own database (PostgreSQL, MySQL, Oracle, MSSQL, DB2, SQLite) or use the wizard, follow [docs/integrate.md](docs/integrate.md).

---

## Two adoption paths

**New project — start with the wizard.** Plain-language entity/relationship/CQ capture. No OWL knowledge required.

```bash
pip install -r requirements-core.txt
python3 onboard.py --industry telecom        # or healthcare / finance / manufacturing / retail
```

**Existing database — point the toolkit at it.** Two small system tables, ~5 metadata rows, one command.

```bash
pip install -r requirements-core.txt -r requirements-db.txt   # add the driver you need
python3 toolkit.py --db "postgresql://user:pass@host/mydb" --out output/
```

Step-by-step for both paths: [docs/integrate.md](docs/integrate.md).

---

## Demos

Three runnable demos under [`examples/`](examples/) — each ~5 seconds, no API keys, illustrative fallback when no LLM keys are set.

| Demo | What it shows | Runner |
|---|---|---|
| [Wizard](examples/wizard/) | Smart Building Operations end-to-end via the onboarding wizard — plain-language → schema → ontology → report | `./examples/wizard/demo_wizard.sh` |
| [Retail](examples/retail/) | Ontology-vs-baseline LLM comparison (8 questions × 2 vendors × 2 modes) | `./examples/retail/demo.sh` |
| [5G Core NFs](examples/5g/) | 3GPP semantic issues — `active` overload, S-NSSAI composition, heartbeat-inferred deregistration | `./examples/5g/demo_5g.sh` |
| [Drift monitoring](examples/infodrift/) | OWL-driven `drift_monitor` (infodrift) integration: discovery, SHACL gating, JSON-LD/PROV-O records, OWL escalation | `./examples/infodrift/demo_infodrift.sh` |

---

## Documentation

| File | When to read |
|---|---|
| **[docs/integrate.md](docs/integrate.md)** | First contact. 5-minute SQLite path, 30-minute existing-DB path, what to ignore |
| **[install.md](install.md)** | Database driver issues, every connection-string format, pip wheel install, full CLI reference |
| **[features.md](features.md)** | What every phase, artifact, and runtime component does — the capability map and reference |
| **[docs/sdk.md](docs/sdk.md)** | Python SDK — `RuntimeClient`, `Grounder`, `InputGate`, `OutputGate`, all adapters |
| [examples/README.md](examples/README.md) | Index of runnable demos |

Companion documents (architects, leadership, governance):

- [docs/framework-whitepaper.md](docs/framework-whitepaper.md) — full framework specification v1.1
- [docs/executive-summary.md](docs/executive-summary.md) — non-technical overview
- [docs/technical-blueprint.md](docs/technical-blueprint.md) — phase-by-phase implementation guide
- [tests/test-plan.md](tests/test-plan.md) · [tests/test-plan-5g.md](tests/test-plan-5g.md) — first-contact test plans
- [ontology_governance_checklist.csv](ontology_governance_checklist.csv) — 34-criterion checklist

---

*Framework v1.1 · Toolkit v3.0 · OWL 2 · SHACL · PROV-O · SKOS · JSON-LD · TM Forum SID v23.0 · 6 database backends · Runtime layer · Generation 2 workstreams 1–5 · Production drift monitoring (infodrift P1–P5) · pip-installable*
