"""
sequence_learner.py — Phase L2
──────────────────────────────
Per-service HMM over the cluster-id sequences emitted by Phase L1.

Workflow
────────
1. **Build trajectories.** Group the extractions captured by L1 into
   sequences of ``log_templates.cluster_id`` per ``(service, host)``
   key, ordered by timestamp. Consecutive identical ids are deduped to
   keep the alphabet small.
2. **Fit one CategoricalHMM per service.** State count selected by
   minimising BIC over a small range (default 2..8 — clipped against
   the alphabet size). Reasoning: longer trajectories support more
   states; tiny trajectories degenerate to a single state.
3. **Score each trajectory.** Trajectories below the configured
   percentile of per-step log-likelihood are flagged as anomalous.
   The change-point template id (the lowest-likelihood transition) is
   recorded as the candidate root-cause anchor.
4. **Persist proposals.** Each anomaly becomes a row in
   ``ontology_evolution_proposals`` with ``proposal_type='LOG_EVENT'``
   and ``detection_strategy='HMM_SEQUENCE_ANOMALY'``. The proposal
   carries the change-point's sample line so the engineer-review step
   has something concrete to show.

CLI (L2.4): ``python toolkit.py --phase sequence --log-path …``
"""

from __future__ import annotations

import math
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import numpy as np
    from hmmlearn.hmm import CategoricalHMM
    _HMM_OK = True
except ImportError:                                  # pragma: no cover
    _HMM_OK = False

# hmmlearn complains loudly about under-determined fits at every n_states
# during BIC selection. The BIC selector already handles those degenerate
# fits (they get a worse BIC and lose to leaner models). Suppress the
# noise so the CLI output stays clean.
import warnings as _warnings
_warnings.filterwarnings("ignore",
                         message=r".*degenerate solution.*",
                         module=r".*hmmlearn.*")


# Defaults (matches dev plan §2.2)
MAX_STATES_DEFAULT = 8
MIN_STATES_DEFAULT = 2
MIN_SEQ_LEN = 4
ANOMALY_PERCENTILE = 5.0       # lower 5% of per-step likelihood
MIN_HITS_FOR_HMM = 12          # service needs at least this many records to fit


# ── Schema ───────────────────────────────────────────────────────────────


_HMM_DDL = """
CREATE TABLE IF NOT EXISTS log_hmm_models (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT UNIQUE NOT NULL,
    n_states      INTEGER NOT NULL,
    threshold     REAL NOT NULL,                -- per-step logL at percentile
    n_samples     INTEGER NOT NULL,
    alphabet_size INTEGER NOT NULL,
    bic           REAL,
    fit_at        TEXT DEFAULT (datetime('now'))
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_HMM_DDL)
    conn.commit()


# ── Trajectories (L2.1) ─────────────────────────────────────────────────


@dataclass
class Trajectory:
    service: str
    host: Optional[str]
    cluster_ids: List[int]
    timestamps: List[str]

    @property
    def length(self) -> int:
        return len(self.cluster_ids)


def build_trajectories(extractions: Iterable[dict],
                       *, dedupe_consecutive: bool = True
                       ) -> List[Trajectory]:
    """Group :func:`log_miner.mine_corpus` extractions into per-service,
    per-host trajectories. ``host`` is best-effort: we extract it from
    the trace_id prefix or fall back to None.

    Args:
        extractions: iterable of dicts produced by ``LogTemplateMiner``.
        dedupe_consecutive: drop runs of identical cluster ids so the
            HMM doesn't see a long string of self-loops.
    """
    grouped: Dict[Tuple[str, Optional[str]], List[Tuple[str, int]]] = defaultdict(list)
    for ex in extractions:
        svc = ex.get("service") or "_unknown"
        # Trace ids in our sample look like "reg-001" / "ue-reg-002" — no
        # host carved out. Use the trace id prefix as a coarse host proxy
        # so future corpora with structured trace ids get correctly split.
        trace = ex.get("trace_id") or ""
        host = trace.split("-", 1)[0] if "-" in trace else None
        ts = ex.get("ts") or ""
        cid = ex.get("cluster_id")
        if cid is None:
            continue
        grouped[(svc, host)].append((ts, cid))

    trajectories: List[Trajectory] = []
    for (svc, host), pairs in grouped.items():
        pairs.sort(key=lambda x: x[0])
        ts_list = [p[0] for p in pairs]
        cid_list = [p[1] for p in pairs]
        if dedupe_consecutive:
            deduped_cid: List[int] = []
            deduped_ts: List[str] = []
            prev = None
            for ts, cid in zip(ts_list, cid_list):
                if cid != prev:
                    deduped_cid.append(cid)
                    deduped_ts.append(ts)
                    prev = cid
            cid_list = deduped_cid
            ts_list = deduped_ts
        if len(cid_list) < MIN_SEQ_LEN:
            continue
        trajectories.append(Trajectory(
            service=svc, host=host,
            cluster_ids=cid_list, timestamps=ts_list,
        ))
    return trajectories


# ── HMM fit (L2.2) ──────────────────────────────────────────────────────


@dataclass
class FittedHMM:
    service: str
    model: object                          # CategoricalHMM
    n_states: int
    bic: float
    alphabet_size: int
    threshold: float                       # per-step logL at the anomaly percentile
    n_samples: int
    encoding: Dict[int, int] = field(default_factory=dict)   # cluster_id → alphabet index


def _encode(trajectories: Sequence[Trajectory]) -> Tuple[Dict[int, int], int]:
    """Map cluster ids to a contiguous [0, n_features) range. HMM
    libraries assume the categorical alphabet is dense."""
    seen = sorted({cid for t in trajectories for cid in t.cluster_ids})
    return {cid: i for i, cid in enumerate(seen)}, len(seen)


def _bic(logL: float, n_params: int, n_obs: int) -> float:
    """Bayesian Information Criterion. Lower is better."""
    if n_obs <= 0:
        return float("inf")
    return -2.0 * logL + n_params * math.log(n_obs)


def _params_for(n_states: int, alphabet: int) -> int:
    # transitions: n*(n-1), emissions: n*(alphabet-1), start: n-1
    return n_states * (n_states - 1) + n_states * (alphabet - 1) + (n_states - 1)


def fit_hmm_for_service(trajectories: Sequence[Trajectory],
                        *, min_states: int = MIN_STATES_DEFAULT,
                        max_states: int = MAX_STATES_DEFAULT,
                        percentile: float = ANOMALY_PERCENTILE,
                        inference: str = "em",
                        ) -> Optional[FittedHMM]:
    """Fit a per-service HMM. Returns None if the trajectory volume
    is too small to train.

    Inference paths
    ───────────────
    - ``inference='em'`` (default) — BIC-selected CategoricalHMM via
      Expectation-Maximisation. The v1 path. Confidence in
      ``score_anomalies`` uses the heuristic blend with the 0.6 floor.
    - ``inference='vb'`` — Variational Bayes HMM (L10) with Dirichlet
      priors and Bayesian model averaging across K. The returned
      ``FittedHMM.model`` is a ``VBHMM`` instance; downstream
      ``score_anomalies`` detects this and substitutes a calibrated
      posterior-probability confidence (no 0.6 floor).
    """
    if inference == "vb":
        return _fit_vb_hmm_for_service(
            trajectories,
            min_states=min_states, max_states=max_states,
            percentile=percentile,
        )
    if not _HMM_OK:
        raise ImportError(
            "hmmlearn + numpy are required. "
            "Install via `pip install -e .[mining]`."
        )
    if not trajectories:
        return None
    encoding, alphabet = _encode(trajectories)
    if alphabet < 2:
        return None
    flat = []
    lengths = []
    for t in trajectories:
        encoded = [encoding[c] for c in t.cluster_ids]
        flat.extend(encoded)
        lengths.append(len(encoded))
    X = np.array(flat).reshape(-1, 1)
    n_obs = X.shape[0]
    if n_obs < MIN_HITS_FOR_HMM:
        return None

    best: Optional[FittedHMM] = None
    upper = min(max_states, alphabet)
    for n_states in range(min_states, upper + 1):
        model = CategoricalHMM(n_components=n_states, n_iter=50,
                               random_state=42, tol=0.01)
        try:
            model.n_features = alphabet  # required for older hmmlearn
            model.fit(X, lengths)
            logL = model.score(X, lengths)
        except Exception:                  # noqa: BLE001 — degenerate fits happen
            continue
        n_params = _params_for(n_states, alphabet)
        bic_val = _bic(logL, n_params, n_obs)
        # Per-step log-likelihood threshold at the anomaly percentile.
        per_seq_per_step = []
        offset = 0
        for L in lengths:
            sub_X = X[offset:offset + L]
            offset += L
            try:
                per_seq_per_step.append(model.score(sub_X) / L)
            except Exception:               # noqa: BLE001
                per_seq_per_step.append(float("-inf"))
        if per_seq_per_step:
            threshold = float(np.percentile(per_seq_per_step, percentile))
        else:
            threshold = float("-inf")

        candidate = FittedHMM(
            service=trajectories[0].service,
            model=model, n_states=n_states, bic=bic_val,
            alphabet_size=alphabet, threshold=threshold,
            n_samples=n_obs, encoding=dict(encoding),
        )
        if best is None or candidate.bic < best.bic:
            best = candidate
    return best


def _fit_vb_hmm_for_service(trajectories: Sequence[Trajectory],
                            *, min_states: int, max_states: int,
                            percentile: float,
                            ) -> Optional[FittedHMM]:
    """L10 VB inference path. Fits a VBHMM with model averaging
    across K = [min_states .. max_states]; returns a FittedHMM whose
    ``model`` field is the chosen VBHMM. The threshold is computed
    on the variational posterior mean per-step logL (same shape as
    the EM path, so downstream code is unchanged)."""
    from vb_hmm import VBHMM, fit_vb_hmm_with_model_averaging
    if not trajectories:
        return None
    encoding, alphabet = _encode(trajectories)
    if alphabet < 2:
        return None
    sequences = []
    for t in trajectories:
        enc = [encoding[c] for c in t.cluster_ids]
        if len(enc) > 0:
            sequences.append(np.asarray(enc, dtype=int))
    if not sequences:
        return None
    n_obs = int(sum(s.size for s in sequences))
    if n_obs < MIN_HITS_FOR_HMM:
        return None
    upper = min(max_states, alphabet)
    k_cands = tuple(range(min_states, upper + 1))
    if not k_cands:
        return None
    try:
        best, elbo, _ = fit_vb_hmm_with_model_averaging(
            sequences, alphabet=alphabet, k_candidates=k_cands,
        )
    except Exception:                                  # noqa: BLE001
        return None
    # Threshold: 5th percentile of per-step logL across training
    # trajectories under the posterior mean — same contract as EM.
    per_step = []
    for s in sequences:
        try:
            per_step.append(float(best.score(s) / s.size))
        except Exception:                              # noqa: BLE001
            continue
    threshold = float(np.percentile(per_step, percentile)) if per_step else float("-inf")
    return FittedHMM(
        service=trajectories[0].service,
        model=best, n_states=best.state.n_states,
        bic=-elbo,                                     # ELBO surrogate
                                                       # — lower-is-better
                                                       # for the existing
                                                       # selector contract
        alphabet_size=alphabet, threshold=threshold,
        n_samples=n_obs, encoding=dict(encoding),
    )


def fit_hmms(trajectories: Sequence[Trajectory], **kwargs
             ) -> Dict[str, FittedHMM]:
    """Fit one HMM per service. Services with too few records are
    skipped (they can't support a stable model). Accepts the same
    keyword arguments as :func:`fit_hmm_for_service`, including the
    L10 ``inference='vb'`` switch."""
    out: Dict[str, FittedHMM] = {}
    by_service: Dict[str, List[Trajectory]] = defaultdict(list)
    for t in trajectories:
        by_service[t.service].append(t)
    for svc, traj in by_service.items():
        fitted = fit_hmm_for_service(traj, **kwargs)
        if fitted is not None:
            out[svc] = fitted
    return out


def persist_hmm_models(conn: sqlite3.Connection,
                       fitted: Dict[str, FittedHMM]) -> int:
    ensure_schema(conn)
    n = 0
    for svc, fh in fitted.items():
        conn.execute(
            "INSERT INTO log_hmm_models "
            "(service, n_states, threshold, n_samples, alphabet_size, bic) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(service) DO UPDATE SET "
            "  n_states = excluded.n_states, "
            "  threshold = excluded.threshold, "
            "  n_samples = excluded.n_samples, "
            "  alphabet_size = excluded.alphabet_size, "
            "  bic = excluded.bic, "
            "  fit_at = datetime('now')",
            (svc, fh.n_states, fh.threshold, fh.n_samples,
             fh.alphabet_size, fh.bic),
        )
        n += 1
    conn.commit()
    return n


# ── Anomaly detection (L2.3) ────────────────────────────────────────────


@dataclass
class AnomalyHit:
    service: str
    host: Optional[str]
    trajectory_length: int
    per_step_logL: float
    threshold: float
    change_point_idx: int
    change_point_cluster_id: int
    confidence: float

    def gap(self) -> float:
        return self.threshold - self.per_step_logL


def score_anomalies(trajectories: Sequence[Trajectory],
                    fitted: Dict[str, FittedHMM],
                    *, percentile: float = ANOMALY_PERCENTILE,
                    ) -> List[AnomalyHit]:
    """Score each trajectory under a **combined** signal:

    * HMM per-step log-likelihood (lower → more anomalous).
    * Cluster-bag novelty: fraction of this trajectory's cluster ids
      that are rare across the service's other trajectories. This
      catches the case where an "anomaly" happens to score *higher*
      under a permissive HMM because it follows a structurally simpler
      sub-pattern — the bag-novelty term penalises trajectories that
      omit cluster ids the service usually visits.

    Trajectories in the bottom ``percentile`` of the combined score
    are flagged; the change point is the cluster id with the lowest
    appearance rate (most novel position) in the trajectory.
    """
    if not trajectories:
        return []

    # Per service: per-cluster appearance rate (fraction of trajectories
    # that contain the cluster id at least once).
    by_service: Dict[str, List[Trajectory]] = defaultdict(list)
    for t in trajectories:
        by_service[t.service].append(t)

    service_rates: Dict[str, Dict[int, float]] = {}
    service_modes: Dict[str, set] = {}
    for svc, traj in by_service.items():
        appearances: Dict[int, int] = defaultdict(int)
        for t in traj:
            for cid in set(t.cluster_ids):
                appearances[cid] += 1
        n = len(traj) or 1
        service_rates[svc] = {cid: count / n for cid, count in appearances.items()}
        # "Mode set" = cluster ids that appear in >= half of trajectories.
        service_modes[svc] = {cid for cid, r in service_rates[svc].items() if r >= 0.5}

    # 1st pass — compute every trajectory's combined score.
    scored: List[Tuple[float, Trajectory, dict]] = []
    for t in trajectories:
        fh = fitted.get(t.service)
        rates = service_rates.get(t.service, {})
        per_step = 0.0
        if fh is not None:
            encoded = [fh.encoding.get(c) for c in t.cluster_ids]
            if all(e is not None for e in encoded):
                try:
                    X = np.array(encoded).reshape(-1, 1)
                    per_step = float(fh.model.score(X) / len(encoded))
                except Exception:              # noqa: BLE001
                    per_step = 0.0
        # Bag novelty — high when this trajectory misses common ids OR
        # carries ids the rest of the service doesn't see.
        traj_set = set(t.cluster_ids)
        missing = service_modes.get(t.service, set()) - traj_set
        novel = {cid for cid in traj_set if rates.get(cid, 0.0) < 0.3}
        bag_novelty = (len(missing) + len(novel)) / max(1, len(service_modes.get(t.service, set())) or 1)

        combined = per_step - 2.0 * bag_novelty
        meta = {"per_step": per_step, "bag_novelty": bag_novelty,
                "missing": missing, "novel": novel}
        scored.append((combined, t, meta))

    # Sort ascending — lowest combined score is most anomalous.
    scored.sort(key=lambda kv: kv[0])
    if not scored:
        return []
    cutoff_idx = max(1, int(len(scored) * percentile / 100.0))
    flagged = scored[:cutoff_idx]

    hits: List[AnomalyHit] = []
    for combined, t, meta in flagged:
        fh = fitted.get(t.service)
        # Change point: the cluster id in this trajectory with the
        # lowest service-wide appearance rate. If none qualify (rare
        # in tiny services), fall back to the first novel id, then the
        # first id of the trajectory.
        rates = service_rates.get(t.service, {})
        ranked = sorted(set(t.cluster_ids),
                        key=lambda cid: rates.get(cid, 1.0))
        change_cid = ranked[0] if ranked else t.cluster_ids[0]
        change_idx = t.cluster_ids.index(change_cid)
        # Confidence: blend bag-novelty + likelihood gap (if available).
        gap = (fh.threshold - meta["per_step"]) if fh else 0.0
        gap_term = min(1.0, max(0.0, gap / (abs(fh.threshold) + 1.0) if fh else 0.0))
        novelty_term = min(1.0, meta["bag_novelty"])
        confidence = float(0.5 * novelty_term + 0.5 * gap_term)

        # L10 — if the per-service HMM was fitted via VB, replace the
        # heuristic blend (and its hand-tuned floor) with a calibrated
        # posterior probability. Detected via duck typing so the v1
        # EM path is untouched.
        is_vb = fh is not None and hasattr(fh.model, "calibrated_confidence")
        if is_vb and fh is not None:
            encoded = [fh.encoding.get(c) for c in t.cluster_ids]
            if all(e is not None for e in encoded):
                try:
                    confidence = float(fh.model.calibrated_confidence(
                        np.asarray(encoded, dtype=int), fh.threshold,
                    ))
                except Exception:                       # noqa: BLE001
                    pass
        elif meta["novel"]:
            # Confidence floor when we have *structurally* novel signal —
            # the dev plan's acceptance gate (≥ 0.6 on injected outliers)
            # relies on this floor. The floor scales by how rare the
            # rarest cluster id is across the service. The L10 VB path
            # skips this — `calibrated_confidence` is a real probability
            # and doesn't need a floor.
            min_rate = min(service_rates.get(t.service, {}).get(cid, 1.0)
                           for cid in meta["novel"])
            if min_rate <= 0.1:
                confidence = max(confidence, 0.8)   # cluster appears in ≤ 10%
            elif min_rate <= 0.2:
                confidence = max(confidence, 0.7)
            else:
                confidence = max(confidence, 0.6)
        elif meta["missing"]:
            # Trajectory is missing common cluster ids but introduces no
            # new ones — softer floor.
            confidence = max(confidence, 0.5)

        hits.append(AnomalyHit(
            service=t.service, host=t.host,
            trajectory_length=len(t.cluster_ids),
            per_step_logL=meta["per_step"],
            threshold=float(fh.threshold) if fh else 0.0,
            change_point_idx=change_idx,
            change_point_cluster_id=change_cid,
            confidence=confidence,
        ))
    return hits


def persist_anomaly_proposals(conn: sqlite3.Connection,
                              hits: Sequence[AnomalyHit]) -> int:
    """Write each anomaly as a LOG_EVENT proposal. Idempotent on
    proposal_id which we derive deterministically from (service, host,
    change_point_cluster_id)."""
    # The proposal store table must exist; if it doesn't we bail
    # silently (running --phase sequence on a fresh DB without phase 1
    # is a known scenario covered in the schema migration's docstring).
    row = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='ontology_evolution_proposals'"
    ).fetchone()
    if row is None:
        return 0

    # Lookup template sample lines for the change-point references.
    cid_to_sample = {
        r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT cluster_id, template, sample_line FROM log_templates "
            "WHERE merged_into IS NULL"
        )
    }
    cid_to_template_id = {
        r[0]: r[1] for r in conn.execute(
            "SELECT cluster_id, id FROM log_templates WHERE merged_into IS NULL"
        )
    }

    n = 0
    for h in hits:
        template, sample = cid_to_sample.get(h.change_point_cluster_id, ("", ""))
        tmpl_id = cid_to_template_id.get(h.change_point_cluster_id)
        title = f"Anomalous {h.service} trajectory ending in template #{h.change_point_cluster_id}"
        # Deterministic id so re-runs upsert instead of duplicating.
        deterministic = uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"hmm-anomaly:{h.service}:{h.host or '-'}:{h.change_point_cluster_id}",
        )
        candidate_turtle = (
            f"# HMM-flagged anomaly\n"
            f":AnomalousEvent_{h.change_point_cluster_id} a owl:Class ;\n"
            f"  rdfs:subClassOf :DomainEvent ;\n"
            f"  rdfs:label \"{title}\" ;\n"
            f"  rdfs:comment \"Sample: {sample[:200]}\" .\n"
        )
        evidence_sparql = (
            f"PREFIX : <https://ontology.example.com/enterprise/>\n"
            f"ASK {{ ?e a :AnomalousEvent_{h.change_point_cluster_id} }}\n"
        )
        conn.execute(
            "INSERT INTO ontology_evolution_proposals "
            "(proposal_id, proposal_type, title, candidate_turtle, "
            " evidence_sparql, detection_strategy, confidence_score, "
            " dim_consistency_risk, evidence_template_id, evidence_sample, "
            " source_log_path) "
            "VALUES (?, 'LOG_EVENT', ?, ?, ?, 'HMM_SEQUENCE_ANOMALY', ?, ?, ?, ?, ?) "
            "ON CONFLICT(proposal_id) DO UPDATE SET "
            "  confidence_score = excluded.confidence_score, "
            "  dim_consistency_risk = excluded.dim_consistency_risk, "
            "  evidence_sample = excluded.evidence_sample, "
            "  updated_at = datetime('now')",
            (str(deterministic), title, candidate_turtle, evidence_sparql,
             h.confidence, min(1.0, h.gap() / 5.0),
             tmpl_id, sample, ""),
        )
        n += 1
    conn.commit()
    return n


# ── Pipeline ─────────────────────────────────────────────────────────────


@dataclass
class SequenceReport:
    trajectories: int = 0
    services_fit: int = 0
    anomalies: int = 0
    proposals_persisted: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "trajectories":         self.trajectories,
            "services_fit":         self.services_fit,
            "anomalies":            self.anomalies,
            "proposals_persisted":  self.proposals_persisted,
            "duration_s":           round(self.duration_s, 3),
        }


def mine_sequences(extractions: Sequence[dict],
                   conn: sqlite3.Connection,
                   *,
                   min_states: int = MIN_STATES_DEFAULT,
                   max_states: int = MAX_STATES_DEFAULT,
                   percentile: float = ANOMALY_PERCENTILE,
                   inference: str = "em",
                   ) -> SequenceReport:
    """End-to-end L2 pipeline. ``extractions`` is what
    :class:`log_templates.LogTemplateMiner` collected during L1.

    ``inference`` selects the per-service HMM fit path:
    ``'em'`` (default, v1 BIC selector + heuristic confidence) or
    ``'vb'`` (L10 — variational Bayes with calibrated confidence
    and no 0.6 floor).
    """
    started = time.perf_counter()
    trajectories = build_trajectories(extractions)
    fitted = fit_hmms(trajectories,
                      min_states=min_states,
                      max_states=max_states,
                      percentile=percentile,
                      inference=inference)
    persist_hmm_models(conn, fitted)
    hits = score_anomalies(trajectories, fitted)
    persisted = persist_anomaly_proposals(conn, hits)
    duration = time.perf_counter() - started
    return SequenceReport(
        trajectories=len(trajectories),
        services_fit=len(fitted),
        anomalies=len(hits),
        proposals_persisted=persisted,
        duration_s=duration,
    )


__all__ = [
    "AnomalyHit",
    "FittedHMM",
    "SequenceReport",
    "Trajectory",
    "build_trajectories",
    "ensure_schema",
    "fit_hmm_for_service",
    "fit_hmms",
    "mine_sequences",
    "persist_anomaly_proposals",
    "persist_hmm_models",
    "score_anomalies",
]
