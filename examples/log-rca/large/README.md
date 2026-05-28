# Large synthetic 5G NF corpus — 6,836 lines

Six JSON-Lines files modelling 30 minutes of activity across a small
5G core/RAN deployment. Used for end-to-end demos of the log-RCA
pipeline (Phases L1–L7) at scale.

| File | Service | Lines | What's in it |
|---|---|--:|---|
| `nrf-registry.jsonl`      | NRF  | 2,431 | NF registration + heartbeats + heartbeat-timeout chains + explicit deregisters + rare crypto-rekey event |
| `amf-ue-control.jsonl`    | AMF  | 1,782 | UE registration (350 success / 14 fail) + context transfers + handovers + anomalous orphaned-context flows |
| `smf-pdu-sessions.jsonl`  | SMF  | 1,382 | PDU-session establish / modify / release (280 success / 14 failed) |
| `upf-data-plane.jsonl`    | UPF  |   619 | GTP-U tunnel activations + SLA-breach cascades + recovery + orphan-session anomalies |
| `nssf-slice-selection.jsonl` | NSSF | 374 | Slice selection across eMBB / URLLC / mIoT / V2X + 2 unknown-SST failures + re-selection on SLA breach |
| `oam-alarms.jsonl`        | OAM  |   248 | Alarm raise / notify / escalate / clear cycles |
| **Total**                 |      | **6,836** | |

## Engineered patterns the pipeline must surface

The corpus is hand-tuned so the mining pipeline produces specific,
verifiable signals — useful for both demo screenshots and CI
acceptance tests.

### Heartbeat-timeout → NF deregister → OAM alarm

Six different NFs (`AMF-02`, `UPF-02`, `SMF-03`, `UPF-04`, `AMF-04`,
`SMF-01`) lose 3 heartbeats each, spread across the 30-minute window.
Each chain looks like:

```
WARN  Missed heartbeat #1 for nfId=UPF-02
WARN  Missed heartbeat #2 for nfId=UPF-02
WARN  Missed heartbeat #3 for nfId=UPF-02
ERROR NFDeregister inferred (heartbeat-timeout) for nfId=UPF-02
… (~2 seconds) …
CRIT  Alarm raised nfId=UPF-02 alarmId=NF_UNREACHABLE severity=CRITICAL
INFO  Alarm notified to OSS for nfId=UPF-02 alarmId=NF_UNREACHABLE
INFO  Alarm escalated to operator for nfId=UPF-02 alarmId=NF_UNREACHABLE
```

The PMI + Granger gate must surface
`alarmId=NF_UNREACHABLE → OSS / notified / operator / escalated` as
high-confidence **LOG_CAUSAL_EDGE** proposals.

### SLA-breach cascade across UPF → NSSF → OAM

Five UPF SLA breaches in the window, each cascading into:

```
WARN  Throughput below SLA sessionId=pdu-…  measuredMbps=8  minMbps=50  (×5)
ERROR SLA aggregate breach detected for sst=1 affectedSessions=5
WARN  SliceReSelection triggered snssai=1-000001 reason=sla_breach
MAJOR Alarm raised sliceType=eMBB alarmId=SLA_BREACH severity=MAJOR
…
INFO  Throughput restored sessionId=pdu-…  measuredMbps=120  (×5)
```

Surfaces as `alarmId=SLA_BREACH → notified / OSS` causal candidates.

### Explicit (planned) NF deregister — a distinct cause code

15 `NFDeregister received … cause=PLANNED_MAINTENANCE` lines that
should **not** be confused with heartbeat-timeout. The L5 starter
rules (`rca-derivation-inferred` / `rca-derivation-measured`) split
the two cases by their causal premise.

### Anomalies the HMM must flag

* 3 × `ContextTransfer aborted … cause=ORPHANED_CONTEXT` — UEs with
  context-transfer attempts that don't fit the normal AMF trajectory.
* 2 × `GTP-U tunnel activated … sessionId=pdu-orphan-…` followed by
  `PDU session lookup failed` — UPF activations against a session
  that was never established.

These are intentional outliers — the dev-plan acceptance gate for L2
says the HMM should flag at least one of them with confidence ≥ 0.6.

### Drift-loop fodder

5 × `NFCryptoRekey scheduled … cipher=AES-256-GCM` — a template that
appears only in this corpus, never elsewhere. After a baseline mine
plus a re-run of `--phase drift-templates`, this template surfaces as
a `DRIFT_ON_NEW_TEMPLATE` proposal.

## How to run the demo

```bash
# 1. Bootstrap: mine templates, slot types, PMI graph, Granger gate.
python toolkit.py --phase mine     --log-path examples/log-rca/large/

# 2. Add HMM anomaly proposals.
python toolkit.py --phase sequence --log-path examples/log-rca/large/

# 3. Launch the wizard; navigate to Step 2.5 Log Discovery.
python wizard/app.py
# → browser: review the ~50 templates, 25 entities, ~1,700 relationships,
#   ~100 causal edges. Approve the heartbeat-timeout and SLA-breach
#   chains as LOG_CAUSAL_EDGE.

# 4. Generate the RCA-shaped ontology + materialise.
python toolkit.py --phase 2
python toolkit.py --phase reason

# 5. (Optional) Open Insights → root-cause preset against any
#    :NF_UNREACHABLE alarm IRI. The materialised graph supplies
#    the :hasCause chain back to the heartbeat-miss template.
```

## Expected numbers (against this corpus, on a developer laptop)

```
records ingested       6,836
templates                 52
slots profiled           101
entity edges           1,843
proposals seeded       1,920
  ├─ events:               52
  ├─ entities:             25
  ├─ relationships:     1,745
  └─ causal edges:         98
HMM anomalies              1
duration                ~0.5 s
```

CI uses the smaller sister corpus at
[../sample/](../sample/) for unit tests; this large corpus is for
demos and stakeholder runs.

## Regeneration

The corpus is committed but fully deterministic — `random.Random(42)`
seeds everything. To regenerate identically:

```bash
python examples/log-rca/large/generate.py
```
