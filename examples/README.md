# Examples & Demos

Runnable demos of the ontology-toolkit. Each subfolder is self-contained — clone the repo, install requirements, then run the entrypoint script from the **repo root**.

| Demo | Domain | What it shows | Entrypoint |
|------|--------|---------------|------------|
| [wizard/](wizard/) | Smart Building Operations | Onboarding wizard end-to-end — plain-language domain → schema → ontology → SHACL → JSON-LD → report, in one command | `./examples/wizard/demo_wizard.sh` |
| [retail/](retail/) | Retail / orders | Ontology-vs-baseline LLM comparison (8 questions × 2 vendors) — does the ontology actually help? | `./examples/retail/demo.sh` |
| [5g/](5g/) | 5G Core NFs (3GPP) | Same comparison harness over telecom data — `active` overload, S-NSSAI composition, heartbeat-inferred deregistration, NR/LTE PM counter collision | `./examples/5g/demo_5g.sh` |
| [infodrift/](infodrift/) | Drift monitoring | OWL-driven drift detection: how the toolkit's ontology drives `drift_monitor` (infodrift) entity registration, SHACL gating, JSON-LD enrichment, and OWL propagation | `./examples/infodrift/demo_infodrift.sh` |

## Running

All demos must be run from the **repo root** so they pick up `db/`, `output/`, `runtime/`, and `toolkit.py`:

```bash
cd /path/to/ontology-toolkit
./examples/retail/demo.sh        # retail
./examples/5g/demo_5g.sh         # 5G
./examples/infodrift/demo_infodrift.sh   # drift integration
```

The shell scripts `cd` to the repo root automatically, so calling them from any cwd works too.

## Layout

```
examples/
├── wizard/                    # onboarding wizard end-to-end
│   ├── README.md
│   ├── demo_wizard.sh
│   └── smart_building_session.json
├── retail/                    # original "first-contact" demo
│   ├── README.md              # engineering guide (was demo.md)
│   ├── demo.sh
│   └── scripts/
│       ├── demo_baseline.py   # raw-SQL → plain LLM
│       ├── demo_grounded.py   # RuntimeClient (ontology + SHACL gate)
│       ├── demo_report.py     # builds comparison.html / executive.html
│       ├── demo_questions.py  # 8-question bank
│       └── demo_illustrative.json
├── 5g/                        # 5G Core NF demo
│   ├── demo_5g.sh
│   └── scripts/
│       ├── demo_5g.py         # baseline / grounded / report (one script)
│       ├── demo_5g_questions.py
│       └── demo_5g_illustrative.json
└── infodrift/                 # drift_monitor (infodrift) integration
    ├── README.md
    ├── demo_infodrift.sh
    └── scripts/
        └── demo_infodrift.py  # OWL-driven entity registration + drift run
```

## Why each demo exists

- **wizard** — proves the wizard is genuinely domain-agnostic. Loads a saved session for a Smart Building Operations domain (not one of the 5 starter templates), runs the full pipeline non-interactively, and shows the resulting OWL/SHACL/JSON-LD/report — all without writing SQL or knowing OWL. The session JSON doubles as a worked example of the wizard's session schema. See [wizard/README.md](wizard/README.md).
- **retail** — the canonical "is the ontology pulling its weight?" experiment. Same questions, same vendors, with and without ontology grounding. Read [retail/README.md](retail/README.md) for the full engineering writeup.
- **5g** — the same harness applied to 3GPP 5G Core data, where overloaded names (`active`, S-NSSAI components) and inferred state (heartbeat-derived deregistration) make the no-ontology baseline visibly fail.
- **infodrift** — shows that *production drift detection* is not bolted on after the fact: the OWL class hierarchy and individuals from `toolkit.py` directly drive which entities `drift_monitor` watches, the SHACL shapes gate the production frames, and JSON-LD/PROV-O wraps every drift report so it lands back in the same observation store as the rest of the toolkit's outputs. See [infodrift/README.md](infodrift/README.md).
