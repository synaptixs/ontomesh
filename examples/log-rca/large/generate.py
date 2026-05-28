#!/usr/bin/env python3
"""
Generate a large (~5,800-line) synthetic 5G-NF log corpus for demos.

Companion to ``examples/log-rca/sample/`` — same shape (JSON-Lines, six
files keyed by service) but at a much larger scale and with engineered
causal patterns the L1–L5 pipeline will surface:

  • Heartbeat-timeout → NF deregister chain. Every 3 missed heartbeats
    for a given NF is followed within ~6 s by an NRF deregister and
    an OAM alarm — a clean Granger-detectable cause→effect.

  • PDU-session establish → modify → release lifecycle, with one in
    twenty sessions ending in a failure (cause=NO_UPF_AVAILABLE).

  • Slice SLA breach (UPF) → NSSF re-selection → OAM alarm. A second
    causal chain that crosses three services.

  • UE registration failures (≈ 4 % rate) with characteristic preceding
    AuthResponse=AUTH_FAILURE lines.

  • A handful of anomalous trajectories: AMF context-transfer with no
    matching deregister, UPF data path activated against a session
    that was never established. These exist so the HMM has genuine
    low-likelihood sequences to flag.

  • A rare template that appears only ~5 times — fodder for the
    drift-detection step (L7) to surface as a "new" candidate after
    a baseline mine.

Run::

    python examples/log-rca/large/generate.py

Outputs into the same directory; the file is fully deterministic
(random.Random(42)) so the demo reproduces.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
START = datetime(2026, 5, 7, 9, 0, 0, tzinfo=timezone.utc)
RNG = random.Random(42)

# ── NF / UE / slice catalogues ─────────────────────────────────────────

AMF_IDS = [f"AMF-{i:02d}" for i in range(1, 6)]
SMF_IDS = [f"SMF-{i:02d}" for i in range(1, 5)]
UPF_IDS = [f"UPF-{i:02d}" for i in range(1, 5)]
NSSF_IDS = ["NSSF-01"]
NRF_IDS = ["NRF-01"]
ALL_NFS = AMF_IDS + SMF_IDS + UPF_IDS

SLICES = [
    ("1-000001", "eMBB",  "prof-eMBB-01"),
    ("2-000001", "URLLC", "prof-URLLC-01"),
    ("3-000001", "mIoT",  "prof-mIoT-01"),
    ("4-000001", "V2X",   "prof-V2X-01"),
]

def make_imsi(i: int) -> str:
    return f"imsi-001010{i:09d}"


# ── Output buckets ─────────────────────────────────────────────────────

BUCKETS: dict[str, list[Tuple[datetime, str, str, str, str]]] = {
    "nrf": [], "amf": [], "smf": [], "upf": [], "nssf": [], "oam": [],
}


def emit(service: str, file_key: str, ts: datetime, severity: str,
         trace_id: str, msg: str) -> None:
    BUCKETS[file_key].append((ts, severity, service, trace_id, msg))


def write_all() -> None:
    """Sort each bucket by timestamp and dump as JSON-Lines."""
    file_map = {
        "nrf":  "nrf-registry.jsonl",
        "amf":  "amf-ue-control.jsonl",
        "smf":  "smf-pdu-sessions.jsonl",
        "upf":  "upf-data-plane.jsonl",
        "nssf": "nssf-slice-selection.jsonl",
        "oam":  "oam-alarms.jsonl",
    }
    for key, name in file_map.items():
        path = os.path.join(HERE, name)
        rows = sorted(BUCKETS[key], key=lambda r: r[0])
        with open(path, "w") as f:
            for ts, sev, svc, trace, msg in rows:
                f.write(json.dumps({
                    "ts":       ts.isoformat(),
                    "severity": sev,
                    "service":  svc,
                    "trace_id": trace,
                    "message":  msg,
                }) + "\n")
        print(f"  wrote {name}  ({len(rows)} lines)")


# ── Pattern generators ─────────────────────────────────────────────────


def nrf_lifecycle_window(t0: datetime) -> datetime:
    """Initial registration burst for every NF. Returns the end time."""
    t = t0
    for i, nf in enumerate(ALL_NFS):
        trace = f"reg-{i:04d}"
        nftype = nf.split("-")[0]
        emit("NRF", "nrf", t, "INFO", trace,
             f"NFRegister received from nfId={nf} nfType={nftype}")
        t += timedelta(milliseconds=RNG.randint(40, 90))
        emit("NRF", "nrf", t, "INFO", trace,
             f"NFProfile validated for nfId={nf}")
        t += timedelta(milliseconds=RNG.randint(10, 30))
        emit("NRF", "nrf", t, "INFO", trace,
             f"NFRegister succeeded for nfId={nf} nfStatus=REGISTERED")
        t += timedelta(milliseconds=RNG.randint(150, 400))
    return t


def nrf_heartbeats(t0: datetime, t_end: datetime,
                   interval_s: int = 10) -> None:
    """Periodic heartbeat lines per NF over the whole window."""
    for nf in ALL_NFS:
        t = t0 + timedelta(seconds=RNG.randint(2, interval_s))
        i = 0
        while t < t_end:
            emit("NRF", "nrf", t, "DEBUG", f"hb-{nf}-{i:04d}",
                 f"Heartbeat received from nfId={nf} interval=10s")
            t += timedelta(seconds=interval_s + RNG.uniform(-0.5, 0.5))
            i += 1


def heartbeat_timeout_chain(t0: datetime, nf: str, idx: int) -> None:
    """Heartbeat-timeout → NF deregister → OAM alarm. The signature
    causal chain the dev plan calls out."""
    trace = f"hb-miss-{nf}-{idx:03d}"
    t = t0
    for missed in range(1, 4):
        emit("NRF", "nrf", t, "WARN", trace,
             f"Missed heartbeat #{missed} for nfId={nf}")
        t += timedelta(seconds=10)
    emit("NRF", "nrf", t, "ERROR", trace,
         f"NFDeregister inferred (heartbeat-timeout) for nfId={nf}")
    # Alarm follows within ~3 seconds.
    t += timedelta(seconds=RNG.uniform(1.5, 3.5))
    alarm_trace = f"alarm-{nf}-{idx:03d}"
    emit("OAM", "oam", t, "CRITICAL", alarm_trace,
         f"Alarm raised nfId={nf} alarmId=NF_UNREACHABLE severity=CRITICAL")
    t += timedelta(seconds=RNG.uniform(0.5, 2.0))
    emit("OAM", "oam", t, "INFO", alarm_trace,
         f"Alarm notified to OSS for nfId={nf} alarmId=NF_UNREACHABLE")
    t += timedelta(seconds=RNG.uniform(2.0, 10.0))
    emit("OAM", "oam", t, "INFO", alarm_trace,
         f"Alarm escalated to operator for nfId={nf} alarmId=NF_UNREACHABLE")


def nrf_explicit_deregisters(t0: datetime, n: int) -> None:
    """Planned deregisters via Nnrf_NFManagement_NFDeregister — these
    should NOT trigger heartbeat-timeout proposals (different cause)."""
    for i in range(n):
        nf = RNG.choice(SMF_IDS + UPF_IDS)
        trace = f"dereg-{i:03d}"
        t = t0 + timedelta(seconds=i * 7 + RNG.uniform(0, 4))
        emit("NRF", "nrf", t, "INFO", trace,
             f"NFDeregister received from nfId={nf} cause=PLANNED_MAINTENANCE")
        t += timedelta(milliseconds=RNG.randint(30, 90))
        emit("NRF", "nrf", t, "INFO", trace,
             f"NFDeregister succeeded for nfId={nf}")


# ── AMF: UE registrations + handovers ─────────────────────────────────


def ue_registration(t0: datetime, ue_idx: int,
                    fail: bool = False) -> datetime:
    ue = make_imsi(ue_idx)
    trace = f"ue-reg-{ue_idx:04d}"
    t = t0
    emit("AMF", "amf", t, "INFO", trace,
         f"InitialUEMessage received for ueId={ue}")
    t += timedelta(milliseconds=RNG.randint(30, 80))
    emit("AMF", "amf", t, "DEBUG", trace,
         f"AuthRequest sent to AUSF for ueId={ue}")
    t += timedelta(milliseconds=RNG.randint(80, 180))
    if fail:
        emit("AMF", "amf", t, "ERROR", trace,
             f"AuthResponse received for ueId={ue} result=AUTH_FAILURE")
        t += timedelta(milliseconds=RNG.randint(10, 30))
        emit("AMF", "amf", t, "ERROR", trace,
             f"Registration rejected for ueId={ue} cause=AUTH_FAILURE")
    else:
        emit("AMF", "amf", t, "DEBUG", trace,
             f"AuthResponse received for ueId={ue} result=SUCCESS")
        t += timedelta(milliseconds=RNG.randint(10, 30))
        emit("AMF", "amf", t, "INFO", trace,
             f"Registration accepted for ueId={ue} registrationState=REGISTERED")
    return t


def context_transfer(t0: datetime, ue_idx: int, idx: int) -> None:
    ue = make_imsi(ue_idx)
    src = RNG.choice(AMF_IDS)
    trace = f"ctx-xfer-{idx:04d}"
    t = t0
    emit("AMF", "amf", t, "INFO", trace,
         f"ContextTransfer requested for ueId={ue} fromAmfId={src}")
    t += timedelta(milliseconds=RNG.randint(80, 200))
    emit("AMF", "amf", t, "INFO", trace,
         f"ContextTransfer completed for ueId={ue}")


def handover_flow(t0: datetime, ue_idx: int, idx: int) -> None:
    """N2 handover sequence — adds variety beyond plain registration."""
    ue = make_imsi(ue_idx)
    src = RNG.choice(AMF_IDS)
    dst = RNG.choice([a for a in AMF_IDS if a != src])
    trace = f"ho-{idx:04d}"
    t = t0
    emit("AMF", "amf", t, "INFO", trace,
         f"HandoverRequired for ueId={ue} sourceAmf={src} targetAmf={dst}")
    t += timedelta(milliseconds=RNG.randint(40, 100))
    emit("AMF", "amf", t, "DEBUG", trace,
         f"HandoverRequest sent to targetAmf={dst} for ueId={ue}")
    t += timedelta(milliseconds=RNG.randint(60, 150))
    emit("AMF", "amf", t, "INFO", trace,
         f"HandoverNotify received from targetAmf={dst} for ueId={ue}")
    t += timedelta(milliseconds=RNG.randint(10, 30))
    emit("AMF", "amf", t, "INFO", trace,
         f"Handover completed for ueId={ue} targetAmf={dst}")


# ── SMF / UPF: PDU sessions + SLA breaches ─────────────────────────────


def pdu_session_lifecycle(t0: datetime, idx: int,
                          fail: bool = False) -> None:
    sess = f"pdu-{idx:05d}"
    slice_choice = RNG.choice(SLICES)
    sst = slice_choice[0].split("-")[0]
    upf = RNG.choice(UPF_IDS)
    trace = f"pdu-{idx:05d}"
    t = t0
    emit("SMF", "smf", t, "INFO", trace,
         f"PDUSessionEstablishment requested sessionId={sess} sst={sst}")
    t += timedelta(milliseconds=RNG.randint(40, 80))
    if fail:
        emit("SMF", "smf", t, "ERROR", trace,
             f"PDUSessionEstablishment failed sessionId={sess} cause=NO_UPF_AVAILABLE")
        return
    emit("SMF", "smf", t, "DEBUG", trace,
         f"UPF selection sessionId={sess} selectedUpf={upf}")
    t += timedelta(milliseconds=RNG.randint(20, 60))
    emit("SMF", "smf", t, "INFO", trace,
         f"PDUSession established sessionId={sess} sessionStatus=ACTIVE")
    # UPF activates the GTP-U tunnel a moment later.
    t += timedelta(milliseconds=RNG.randint(30, 80))
    upf_trace = f"upf-act-{idx:05d}"
    emit("UPF", "upf", t, "INFO", upf_trace,
         f"GTP-U tunnel activated sessionId={sess} teid=0x{idx:08x}")
    t += timedelta(milliseconds=RNG.randint(10, 30))
    emit("UPF", "upf", t, "DEBUG", upf_trace,
         f"Data path enabled sessionId={sess}")

    # A modify event for some sessions.
    if RNG.random() < 0.35:
        t += timedelta(seconds=RNG.uniform(8, 30))
        mod_trace = f"pdu-mod-{idx:05d}"
        emit("SMF", "smf", t, "INFO", mod_trace,
             f"PDUSessionModification requested sessionId={sess} reason=qos_update")
        t += timedelta(milliseconds=RNG.randint(30, 90))
        emit("SMF", "smf", t, "INFO", mod_trace,
             f"PDUSession modified sessionId={sess} sessionStatus=ACTIVE")

    # A release event for some sessions.
    if RNG.random() < 0.6:
        t += timedelta(seconds=RNG.uniform(20, 120))
        rel_trace = f"pdu-rel-{idx:05d}"
        emit("SMF", "smf", t, "INFO", rel_trace,
             f"PDUSessionRelease requested sessionId={sess} cause=normal")
        t += timedelta(milliseconds=RNG.randint(30, 80))
        emit("SMF", "smf", t, "INFO", rel_trace,
             f"PDUSession released sessionId={sess} sessionStatus=RELEASED")


def sla_breach_cascade(t0: datetime, slice_idx: int) -> None:
    """UPF SLA breach → NSSF re-selection log → OAM alarm. Three-service
    causal chain."""
    snssai, label, prof = SLICES[slice_idx % len(SLICES)]
    t = t0
    sess_ids = [f"pdu-{RNG.randint(1, 9999):05d}" for _ in range(5)]
    for i, sess in enumerate(sess_ids):
        emit("UPF", "upf", t + timedelta(seconds=i * 0.4), "WARN",
             f"sla-breach-{slice_idx}-{i}",
             f"Throughput below SLA sessionId={sess} measuredMbps={RNG.randint(5, 15)} minMbps=50")
    t += timedelta(seconds=2.5)
    emit("UPF", "upf", t, "ERROR", f"sla-aggregate-{slice_idx}",
         f"SLA aggregate breach detected for sst={snssai.split('-')[0]} affectedSessions={len(sess_ids)}")
    # NSSF reaction.
    t += timedelta(seconds=RNG.uniform(0.5, 2.0))
    emit("NSSF", "nssf", t, "WARN", f"slice-reselect-{slice_idx}",
         f"SliceReSelection triggered snssai={snssai} reason=sla_breach")
    t += timedelta(milliseconds=RNG.randint(30, 70))
    emit("NSSF", "nssf", t, "INFO", f"slice-reselect-{slice_idx}",
         f"SliceProfile resolved snssai={snssai} sliceType={label}")
    # OAM alarm.
    t += timedelta(seconds=RNG.uniform(0.8, 2.5))
    alarm_trace = f"alarm-sla-{slice_idx}"
    emit("OAM", "oam", t, "MAJOR", alarm_trace,
         f"Alarm raised sliceType={label} alarmId=SLA_BREACH severity=MAJOR")
    t += timedelta(seconds=RNG.uniform(8, 30))
    emit("OAM", "oam", t, "INFO", alarm_trace,
         f"Alarm cleared sliceType={label} alarmId=SLA_BREACH cause=throughput_restored")
    # Recovery messages on UPF.
    for i, sess in enumerate(sess_ids):
        t += timedelta(seconds=RNG.uniform(0.3, 0.9))
        emit("UPF", "upf", t, "INFO", f"sla-recovery-{slice_idx}-{i}",
             f"Throughput restored sessionId={sess} measuredMbps={RNG.randint(80, 180)}")


# ── NSSF: routine slice selection ──────────────────────────────────────


def slice_selection(t0: datetime, idx: int, unknown: bool = False) -> None:
    if unknown:
        trace = f"slice-fail-{idx:03d}"
        snssai = f"{RNG.randint(90, 99)}-000001"
        t = t0
        emit("NSSF", "nssf", t, "WARN", trace,
             f"SliceSelection requested snssai={snssai}")
        t += timedelta(milliseconds=RNG.randint(10, 25))
        emit("NSSF", "nssf", t, "ERROR", trace,
             f"SliceProfile lookup failed snssai={snssai} cause=UNKNOWN_SST")
        return
    snssai, label, prof = RNG.choice(SLICES)
    trace = f"slice-sel-{idx:04d}"
    t = t0
    emit("NSSF", "nssf", t, "INFO", trace,
         f"SliceSelection requested snssai={snssai}")
    t += timedelta(milliseconds=RNG.randint(10, 30))
    emit("NSSF", "nssf", t, "DEBUG", trace,
         f"SliceProfile resolved snssai={snssai} sliceType={label}")
    t += timedelta(milliseconds=RNG.randint(15, 40))
    emit("NSSF", "nssf", t, "INFO", trace,
         f"SliceSelection completed snssai={snssai} sliceProfileId={prof}")


# ── OAM: routine alarm clears ─────────────────────────────────────────


def routine_alarm_clear(t0: datetime, idx: int) -> None:
    cell = f"cell-{idx:04d}"
    emit("OAM", "oam", t0, "INFO", f"alarm-clear-{idx:04d}",
         f"Alarm cleared cellId={cell} alarmId=NEIGHBOR_RELATION_STALE")


# ── Anomalies (low-likelihood trajectories for HMM to flag) ───────────


def anomaly_context_transfer_no_dereg(t0: datetime, idx: int) -> None:
    """Context transfer for a UE without any subsequent dereg or
    registration — an unusual partial flow."""
    ue = make_imsi(900_000 + idx)
    src = RNG.choice(AMF_IDS)
    trace = f"anom-ctx-{idx:03d}"
    t = t0
    emit("AMF", "amf", t, "WARN", trace,
         f"ContextTransfer requested for ueId={ue} fromAmfId={src}")
    t += timedelta(milliseconds=RNG.randint(60, 150))
    emit("AMF", "amf", t, "ERROR", trace,
         f"ContextTransfer aborted for ueId={ue} cause=ORPHANED_CONTEXT")


def anomaly_data_path_no_session(t0: datetime, idx: int) -> None:
    """UPF activates a data path against a session that was never
    established. Trips the HMM bag-novelty term."""
    sess = f"pdu-orphan-{idx:04d}"
    trace = f"anom-orphan-{idx:03d}"
    t = t0
    emit("UPF", "upf", t, "ERROR", trace,
         f"GTP-U tunnel activated sessionId={sess} teid=0xdeadbeef")
    t += timedelta(milliseconds=RNG.randint(20, 60))
    emit("UPF", "upf", t, "ERROR", trace,
         f"PDU session lookup failed sessionId={sess}")


# ── Rare template (drift fodder) ───────────────────────────────────────


def rare_event(t0: datetime, idx: int) -> None:
    """Five-line trickle of a template that doesn't appear elsewhere.
    A baseline mine catches it (≥ 3 hits) but it's a distinct shape
    that won't accidentally cluster with the common templates."""
    t = t0
    emit("NRF", "nrf", t, "WARN", f"crypto-rekey-{idx:03d}",
         f"NFCryptoRekey scheduled tenantId=tenant-{idx:03d} cipher=AES-256-GCM")


# ── Compose the full corpus ────────────────────────────────────────────


def main() -> None:
    # Total simulated window: ~30 minutes.
    t_window_end = START + timedelta(minutes=30)

    # 1. NRF initial registration burst.
    t_after_reg = nrf_lifecycle_window(START)

    # 2. Continuous heartbeat traffic across the window.
    nrf_heartbeats(t_after_reg, t_window_end, interval_s=10)

    # 3. Heartbeat-timeout chains (the showcase causal pattern).
    #    Six different NFs lose heartbeats, spread across the window.
    chain_targets = ["AMF-02", "UPF-02", "SMF-03", "UPF-04", "AMF-04", "SMF-01"]
    for i, nf in enumerate(chain_targets):
        t = START + timedelta(minutes=2 + i * 4,
                              seconds=RNG.randint(0, 90))
        heartbeat_timeout_chain(t, nf, i)

    # 4. Explicit (planned) deregisters — distinct cause code.
    nrf_explicit_deregisters(START + timedelta(minutes=8), n=15)

    # 5. UE registrations — 350 successful + 14 failures (≈ 4 %).
    for i in range(350):
        t = START + timedelta(seconds=RNG.uniform(20, 1750))
        ue_registration(t, i, fail=False)
    for i in range(14):
        t = START + timedelta(seconds=RNG.uniform(60, 1700))
        ue_registration(t, 900 + i, fail=True)

    # 6. Context transfers + handovers.
    for i in range(80):
        t = START + timedelta(seconds=RNG.uniform(40, 1750))
        context_transfer(t, RNG.randint(0, 349), i)
    for i in range(40):
        t = START + timedelta(seconds=RNG.uniform(60, 1700))
        handover_flow(t, RNG.randint(0, 349), i)

    # 7. PDU session lifecycles — 280 successful + 14 failures.
    for i in range(280):
        t = START + timedelta(seconds=RNG.uniform(30, 1700))
        pdu_session_lifecycle(t, i, fail=False)
    for i in range(14):
        t = START + timedelta(seconds=RNG.uniform(60, 1700))
        pdu_session_lifecycle(t, 9000 + i, fail=True)

    # 8. SLA-breach cascades — five events spaced across the window.
    for i in range(5):
        t = START + timedelta(minutes=4 + i * 5, seconds=RNG.randint(0, 60))
        sla_breach_cascade(t, i)

    # 9. Routine slice-selection chatter.
    for i in range(120):
        t = START + timedelta(seconds=RNG.uniform(20, 1780))
        slice_selection(t, i, unknown=False)
    # Two "unknown SST" failures.
    for i in range(2):
        t = START + timedelta(seconds=RNG.uniform(120, 1700))
        slice_selection(t, 200 + i, unknown=True)

    # 10. Routine OAM alarm clears (cell-housekeeping noise).
    for i in range(220):
        t = START + timedelta(seconds=RNG.uniform(15, 1790))
        routine_alarm_clear(t, i)

    # 11. Anomaly trajectories — keep these rare.
    for i in range(3):
        t = START + timedelta(minutes=12 + i * 5, seconds=RNG.randint(0, 30))
        anomaly_context_transfer_no_dereg(t, i)
    for i in range(2):
        t = START + timedelta(minutes=18 + i * 4, seconds=RNG.randint(0, 30))
        anomaly_data_path_no_session(t, i)

    # 12. Rare template (drift fodder).
    for i in range(5):
        t = START + timedelta(minutes=14, seconds=i * 3 + RNG.randint(0, 5))
        rare_event(t, i)

    # Write everything.
    write_all()
    total = sum(len(b) for b in BUCKETS.values())
    print(f"\n  total lines: {total}")


if __name__ == "__main__":
    main()
