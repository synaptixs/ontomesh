#!/usr/bin/env python3
"""
Regenerate the synthetic 5G NF log fixtures next to this file.

Idempotent — overwrites the six .jsonl files in this directory with the
exact same content every run (deterministic timestamps + iteration).
The committed .jsonl files are the source of truth for tests; this
script exists so we can reproduce them after a schema change.

Usage:
    python examples/log-rca/sample/generate.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
START = datetime(2026, 5, 7, 9, 0, 0, tzinfo=timezone.utc)


def _line(ts, severity, service, trace_id, message):
    return json.dumps({
        "ts": ts.isoformat(),
        "severity": severity,
        "service": service,
        "trace_id": trace_id,
        "message": message,
    })


def _write(name, lines):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        for ln in lines:
            f.write(ln + "\n")
    print(f"  wrote {name}  ({len(lines)} lines)")


# ── NRF (Network Repository Function) ────────────────────────────────────


def nrf_registration():
    lines = []
    nf_ids = ["AMF-01", "AMF-02", "SMF-01", "UPF-01", "UPF-02"]
    ts = START
    for i, nf in enumerate(nf_ids):
        # Registration sequence
        lines.append(_line(ts, "INFO", "NRF", f"reg-{i:03d}",
                           f"NFRegister received from nfId={nf} nfType={nf.split('-')[0]}"))
        ts += timedelta(milliseconds=80)
        lines.append(_line(ts, "INFO", "NRF", f"reg-{i:03d}",
                           f"NFProfile validated for nfId={nf}"))
        ts += timedelta(milliseconds=20)
        lines.append(_line(ts, "INFO", "NRF", f"reg-{i:03d}",
                           f"NFRegister succeeded for nfId={nf} nfStatus=REGISTERED"))
        ts += timedelta(seconds=2)
        # Heartbeat run
        for hb in range(4):
            lines.append(_line(ts, "DEBUG", "NRF", f"hb-{i}-{hb}",
                               f"Heartbeat received from nfId={nf} interval=10s"))
            ts += timedelta(seconds=10)
    # Two NFs miss heartbeats
    for nf in ["UPF-02", "AMF-02"]:
        for missed in range(3):
            ts += timedelta(seconds=10)
            lines.append(_line(ts, "WARN", "NRF", f"hb-miss-{nf}",
                               f"Missed heartbeat #{missed+1} for nfId={nf}"))
        ts += timedelta(seconds=1)
        lines.append(_line(ts, "ERROR", "NRF", f"hb-miss-{nf}",
                           f"NFDeregister inferred (heartbeat-timeout) for nfId={nf}"))
    # And one explicit deregister
    ts += timedelta(seconds=5)
    lines.append(_line(ts, "INFO", "NRF", "dereg-001",
                       "NFDeregister received from nfId=SMF-01 cause=PLANNED_MAINTENANCE"))
    ts += timedelta(milliseconds=40)
    lines.append(_line(ts, "INFO", "NRF", "dereg-001",
                       "NFDeregister succeeded for nfId=SMF-01"))
    return lines


# ── AMF (Access and Mobility Function) ───────────────────────────────────


def amf_registration():
    lines = []
    ts = START + timedelta(seconds=5)
    for i in range(8):
        ue = f"imsi-001010000000{i:03d}"
        trace = f"ue-reg-{i:03d}"
        lines.append(_line(ts, "INFO", "AMF", trace,
                           f"InitialUEMessage received for ueId={ue}"))
        ts += timedelta(milliseconds=50)
        lines.append(_line(ts, "DEBUG", "AMF", trace,
                           f"AuthRequest sent to AUSF for ueId={ue}"))
        ts += timedelta(milliseconds=120)
        lines.append(_line(ts, "DEBUG", "AMF", trace,
                           f"AuthResponse received for ueId={ue} result=SUCCESS"))
        ts += timedelta(milliseconds=30)
        lines.append(_line(ts, "INFO", "AMF", trace,
                           f"Registration accepted for ueId={ue} registrationState=REGISTERED"))
        ts += timedelta(seconds=1)
    # One failed registration
    ue = "imsi-001010000099X"
    trace = "ue-reg-fail-099"
    ts += timedelta(seconds=2)
    lines.append(_line(ts, "INFO", "AMF", trace,
                       f"InitialUEMessage received for ueId={ue}"))
    ts += timedelta(milliseconds=80)
    lines.append(_line(ts, "ERROR", "AMF", trace,
                       f"AuthResponse received for ueId={ue} result=AUTH_FAILURE"))
    ts += timedelta(milliseconds=20)
    lines.append(_line(ts, "ERROR", "AMF", trace,
                       f"Registration rejected for ueId={ue} cause=AUTH_FAILURE"))
    # Context transfers
    for i in range(5):
        trace = f"ctx-xfer-{i:03d}"
        ts += timedelta(seconds=3)
        lines.append(_line(ts, "INFO", "AMF", trace,
                           f"ContextTransfer requested for ueId=imsi-00101000000{i+10:02d} fromAmfId=AMF-01"))
        ts += timedelta(milliseconds=100)
        lines.append(_line(ts, "INFO", "AMF", trace,
                           f"ContextTransfer completed for ueId=imsi-00101000000{i+10:02d}"))
    return lines


# ── SMF (Session Management Function) ────────────────────────────────────


def smf_pdu():
    lines = []
    ts = START + timedelta(seconds=10)
    for i in range(7):
        sess = f"pdu-{i:04d}"
        trace = f"pdu-est-{i:03d}"
        lines.append(_line(ts, "INFO", "SMF", trace,
                           f"PDUSessionEstablishment requested sessionId={sess} sst=1"))
        ts += timedelta(milliseconds=60)
        lines.append(_line(ts, "DEBUG", "SMF", trace,
                           f"UPF selection sessionId={sess} selectedUpf=UPF-01"))
        ts += timedelta(milliseconds=40)
        lines.append(_line(ts, "INFO", "SMF", trace,
                           f"PDUSession established sessionId={sess} sessionStatus=ACTIVE"))
        ts += timedelta(seconds=2)
    # Modify + release
    for i in range(3):
        sess = f"pdu-{i:04d}"
        trace = f"pdu-mod-{i:03d}"
        ts += timedelta(seconds=1)
        lines.append(_line(ts, "INFO", "SMF", trace,
                           f"PDUSessionModification requested sessionId={sess} reason=qos_update"))
        ts += timedelta(milliseconds=50)
        lines.append(_line(ts, "INFO", "SMF", trace,
                           f"PDUSession modified sessionId={sess} sessionStatus=ACTIVE"))
    # Releases
    for i in range(2):
        sess = f"pdu-{i:04d}"
        trace = f"pdu-rel-{i:03d}"
        ts += timedelta(seconds=2)
        lines.append(_line(ts, "INFO", "SMF", trace,
                           f"PDUSessionRelease requested sessionId={sess} cause=normal"))
        ts += timedelta(milliseconds=40)
        lines.append(_line(ts, "INFO", "SMF", trace,
                           f"PDUSession released sessionId={sess} sessionStatus=RELEASED"))
    # One failure
    trace = "pdu-fail-999"
    ts += timedelta(seconds=3)
    lines.append(_line(ts, "ERROR", "SMF", trace,
                       "PDUSessionEstablishment failed sessionId=pdu-9999 cause=NO_UPF_AVAILABLE"))
    return lines


# ── UPF (User Plane Function) ────────────────────────────────────────────


def upf_data():
    lines = []
    ts = START + timedelta(seconds=15)
    for i in range(8):
        sess = f"pdu-{i:04d}"
        trace = f"upf-act-{i:03d}"
        lines.append(_line(ts, "INFO", "UPF", trace,
                           f"GTP-U tunnel activated sessionId={sess} teid=0x{i:08x}"))
        ts += timedelta(milliseconds=30)
        lines.append(_line(ts, "DEBUG", "UPF", trace,
                           f"Data path enabled sessionId={sess}"))
        ts += timedelta(seconds=2)
    # SLA-breach burst
    for i in range(5):
        trace = f"sla-breach-{i:03d}"
        ts += timedelta(seconds=1)
        lines.append(_line(ts, "WARN", "UPF", trace,
                           f"Throughput below SLA sessionId=pdu-{i:04d} measuredMbps=8 minMbps=50"))
    ts += timedelta(seconds=2)
    lines.append(_line(ts, "ERROR", "UPF", "sla-aggregate",
                       "SLA aggregate breach detected for sst=1 affectedSessions=5"))
    # Recovery
    for i in range(5):
        ts += timedelta(seconds=1)
        lines.append(_line(ts, "INFO", "UPF", f"sla-recovery-{i:03d}",
                           f"Throughput restored sessionId=pdu-{i:04d} measuredMbps=120"))
    return lines


# ── NSSF (Network Slice Selection Function) ─────────────────────────────


def nssf_slice():
    lines = []
    ts = START + timedelta(seconds=8)
    profiles = [("1-000001", "eMBB"), ("2-000001", "URLLC"),
                ("3-000001", "mIoT"),  ("4-000001", "V2X")]
    for i, (snssai, label) in enumerate(profiles * 3):
        trace = f"slice-sel-{i:03d}"
        lines.append(_line(ts, "INFO", "NSSF", trace,
                           f"SliceSelection requested snssai={snssai}"))
        ts += timedelta(milliseconds=20)
        lines.append(_line(ts, "DEBUG", "NSSF", trace,
                           f"SliceProfile resolved snssai={snssai} sliceType={label}"))
        ts += timedelta(milliseconds=30)
        lines.append(_line(ts, "INFO", "NSSF", trace,
                           f"SliceSelection completed snssai={snssai} sliceProfileId=prof-{label}-01"))
        ts += timedelta(seconds=1)
    # Mismatch case (sst=99 unknown)
    ts += timedelta(seconds=2)
    lines.append(_line(ts, "WARN", "NSSF", "slice-fail-1",
                       "SliceSelection requested snssai=99-000001"))
    ts += timedelta(milliseconds=15)
    lines.append(_line(ts, "ERROR", "NSSF", "slice-fail-1",
                       "SliceProfile lookup failed snssai=99-000001 cause=UNKNOWN_SST"))
    return lines


# ── OAM alarm stream ─────────────────────────────────────────────────────


def alarm_stream():
    lines = []
    ts = START + timedelta(seconds=30)
    # Alarms triggered by upstream NRF heartbeat-timeout events
    for nf in ["UPF-02", "AMF-02"]:
        lines.append(_line(ts, "CRITICAL", "OAM", f"alarm-{nf}",
                           f"Alarm raised nfId={nf} alarmId=NF_UNREACHABLE severity=CRITICAL"))
        ts += timedelta(seconds=2)
        lines.append(_line(ts, "INFO", "OAM", f"alarm-{nf}",
                           f"Alarm notified to OSS for nfId={nf} alarmId=NF_UNREACHABLE"))
        ts += timedelta(seconds=4)
        lines.append(_line(ts, "INFO", "OAM", f"alarm-{nf}",
                           f"Alarm escalated to operator for nfId={nf} alarmId=NF_UNREACHABLE"))
        ts += timedelta(seconds=10)
    # SLA alarm (UPF → OAM)
    ts += timedelta(seconds=5)
    lines.append(_line(ts, "WARN", "OAM", "alarm-sla-1",
                       "Alarm raised sliceType=eMBB alarmId=SLA_BREACH severity=MAJOR"))
    ts += timedelta(seconds=12)
    lines.append(_line(ts, "INFO", "OAM", "alarm-sla-1",
                       "Alarm cleared sliceType=eMBB alarmId=SLA_BREACH cause=throughput_restored"))
    # Routine clears
    for i in range(20):
        ts += timedelta(seconds=2)
        lines.append(_line(ts, "INFO", "OAM", f"alarm-clear-{i:03d}",
                           f"Alarm cleared cellId=cell-{i:03d} alarmId=NEIGHBOR_RELATION_STALE"))
    return lines


# ── main ─────────────────────────────────────────────────────────────────


def main():
    _write("nrf-registration.jsonl", nrf_registration())
    _write("amf-registration.jsonl", amf_registration())
    _write("smf-pdu.jsonl",          smf_pdu())
    _write("upf-data.jsonl",         upf_data())
    _write("nssf-slice.jsonl",       nssf_slice())
    _write("alarm-stream.jsonl",     alarm_stream())


if __name__ == "__main__":
    main()
