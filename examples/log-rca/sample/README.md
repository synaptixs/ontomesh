# Sample log corpus — synthetic 5G NF events

Six JSON-Lines files modelling a 5G core network's day in the life. Used by:

- `tests/test_log_corpus.py` / `test_log_templates.py` / `test_log_miner.py` — unit-level fixtures.
- `docs/log-rca-dev-plan.md §1.8` — defaults tuning corpus.
- `docs/log-rca-dev-plan.md §11` — demo runbook for the L1 milestone.

Every line is `{"ts": ISO-8601, "severity": ..., "service": ..., "trace_id": ..., "message": "..."}`.

| File | Service | Lines | What's in it |
|---|---|--:|---|
| `nrf-registration.jsonl` | NRF | ~55 | NF registration + heartbeat success/timeout + deregister |
| `amf-registration.jsonl` | AMF | ~55 | UE registration / authentication / context transfer |
| `smf-pdu.jsonl` | SMF | ~55 | PDU-session establish / modify / release |
| `upf-data.jsonl` | UPF | ~55 | Data-path activate / GTP-U tunnel events / SLA breach |
| `nssf-slice.jsonl` | NSSF | ~55 | Slice selection (eMBB / URLLC / mIoT) + S-NSSAI lookup |
| `alarm-stream.jsonl` | OAM | ~55 | Alarm raise / clear / escalation across all services |

Patterns deliberately included so the miner has things to find:

- **Heartbeat → timeout → deregister** chain (the 3GPP R4 "implicit vs explicit deregister" case).
- **PDU-session establish → release** with cause codes.
- **Slice SLA breach** crossing service boundaries (UPF → NSSF).
- **Alarms** that arrive *after* a corresponding NRF deregister — feeds the causality miner (L3).

Regenerate with: `python examples/log-rca/sample/generate.py` (sentinel script — kept for reproducibility; the committed `.jsonl` files are the source of truth for tests).
