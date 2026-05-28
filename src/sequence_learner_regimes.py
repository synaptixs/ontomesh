"""
sequence_learner_regimes.py — Phase L8
──────────────────────────────────────
Switching state-space sequence model for the Log Discovery review queue.

Why this exists
───────────────
The v1 ``sequence_learner`` fits one CategoricalHMM per service, which
averages over distinct operating modes (business hours, weekend
maintenance, incident response). Patterns that are *normal for one mode
but rare across the average* surface as false-positive anomalies. The
roadmap §2.1 calls this out as the largest single source of review-queue
noise.

Model
─────
A **mixture of CategoricalHMMs** per service, with a per-trajectory
regime indicator ``z_n ∈ {1..K}``:

  π    ~ Dirichlet(α_0)
  for k = 1..K:
      HMM_k ~ standard CategoricalHMM params (start / trans / emit)
  for trajectory n:
      z_n ~ Categorical(π)
      x_n ~ HMM_{z_n}(·)

This is the **per-trajectory regime** specialisation of the full
switching SSM (Bishop §13.3.3). Per-timestep VB-SSM is exponential in
sequence length and unstable on log-corpus sizes; per-trajectory
regimes preserve the acceptance-gate semantics ("Regime 2 only") at
polynomial cost and survive hmmlearn's API constraints.

Variational mean-field inference
────────────────────────────────
Factorisation::

    q(z, π) = q(π) Π_n q(z_n)

with q(π) = Dirichlet, q(z_n) = Categorical, and the per-regime
HMM parameters left as MAP point estimates (re-fit each iteration
on the hard-assigned subset — the trade-off documented inline below).

Stopping criterion (per §8 Q5 decision): ``ELBO Δ < 1e-4``, max 200
iterations, 3 random restarts per K.

K selection: sweep K = 1..K_MAX, take the K with the largest ELBO.
A regime is rejected as degenerate if it claims fewer than
``MIN_TRAJ_PER_REGIME`` trajectories at the end of inference; the
candidate K then loses to a smaller K. This matches §6's
"Regime overfitting" mitigation.

Persistence
───────────
- ``log_regime_models(service, n_regimes, model_blob, fit_at)`` — pickle
  of the per-service mixture model.
- ``log_trajectory_regimes(trajectory_id, regime_id, posterior)`` —
  per-trajectory regime assignment with the soft responsibility.

The deterministic ``trajectory_id`` is ``uuid5`` over
``(service, host, first_ts, last_ts, length)`` so re-runs upsert
assignments rather than duplicate them.
"""

from __future__ import annotations

import math
import pickle
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import numpy as np
    from hmmlearn.hmm import CategoricalHMM
    from scipy.special import digamma, logsumexp
    _OK = True
except ImportError:                                  # pragma: no cover
    _OK = False

# v1 lives next door — re-use trajectory + encoding utilities so we
# don't drift away from its definitions of "service" and "alphabet".
from sequence_learner import (
    MIN_HITS_FOR_HMM, MIN_SEQ_LEN, Trajectory,
    build_trajectories, _encode,
)


# ── Defaults (per §8 decisions) ──────────────────────────────────────────

K_MAX = 5                 # Q1: K learned via ELBO, capped K ≤ 5.
N_RESTARTS = 3            # Q5: 3 random restarts per (K, EM) fit.
ELBO_TOL = 1e-4           # Q5: ELBO change threshold.
MAX_VB_ITER = 200         # Q5: max VB iterations.
MIN_TRAJ_PER_REGIME = 2   # Reject K if any regime claims fewer.
MIN_TRAJ_PER_SERVICE = 4  # Need at least this many trajectories to mix.
DIRICHLET_PRIOR = 1.0     # α_0 — symmetric, weakly informative.
HMM_STATES_PER_REGIME = 2 # Each regime gets a fixed-state HMM. Two
                          # states is enough to capture "this regime
                          # visits its own pattern of templates" — going
                          # larger over-parameterises on small per-regime
                          # subsets and triggers degenerate-fit warnings.


# ── Persistence-only dataclasses ─────────────────────────────────────────


@dataclass
class RegimeHMM:
    """Per-regime CategoricalHMM and its training context. We persist
    the hmmlearn model pickled inside `RegimeModel.model_blob`."""
    model: Any                                 # hmmlearn.CategoricalHMM
    n_states: int
    n_train_trajectories: int                  # how many trajectories
                                               # voted for this regime
                                               # at convergence
    per_step_threshold: float                  # 5th-percentile per-step
                                               # logL among assigned trajs
                                               # — the anomaly cutoff


@dataclass
class RegimeModel:
    service: str
    n_regimes: int                             # K (post-rejection)
    alphabet_size: int
    encoding: Dict[int, int]                   # cluster_id → alphabet idx
    regimes: List[RegimeHMM]
    mixing_alpha: List[float]                  # posterior Dirichlet params
    elbo: float
    n_iter: int                                # iterations taken to converge

    def regime_mean_pi(self) -> List[float]:
        s = sum(self.mixing_alpha) or 1.0
        return [a / s for a in self.mixing_alpha]


@dataclass
class TrajectoryRegimeAssignment:
    trajectory_id: str
    service: str
    host: Optional[str]
    regime_id: int                             # argmax over q(z_n)
    posterior: float                           # max r_{n, k}
    full_posteriors: List[float]               # q(z_n) over all K


# ── Helpers ──────────────────────────────────────────────────────────────


def _trajectory_id(t: Trajectory) -> str:
    """Stable identifier for a trajectory across re-runs. Keyed on
    (service, host, first_ts, last_ts, length) — the same trajectory
    will be reseed-stable as long as those five attributes don't shift."""
    first = t.timestamps[0] if t.timestamps else ""
    last = t.timestamps[-1] if t.timestamps else ""
    return str(uuid.uuid5(
        uuid.NAMESPACE_DNS,
        f"traj:{t.service}:{t.host or '-'}:{first}:{last}:{t.length}",
    ))


def _encode_trajectory(t: Trajectory, encoding: Dict[int, int]) -> np.ndarray:
    return np.array([encoding[c] for c in t.cluster_ids
                     if c in encoding]).reshape(-1, 1)


def _fit_single_hmm(X: np.ndarray, lengths: List[int],
                    alphabet: int, n_states: int,
                    random_state: int) -> Optional[Any]:
    """Try to fit a single CategoricalHMM. Returns None if the fit
    degenerates (under-determined start probs, NaN params, etc.).
    Centralises the hmmlearn try/except boilerplate."""
    if not lengths:
        return None
    try:
        model = CategoricalHMM(
            n_components=n_states, n_iter=40, tol=0.01,
            random_state=random_state,
        )
        model.n_features = alphabet
        model.fit(X, lengths)
        return model
    except Exception:                                  # noqa: BLE001
        return None


def _hmm_logL_per_trajectory(model: Any,
                             encoded: Sequence[np.ndarray]) -> np.ndarray:
    """Score each trajectory under one HMM. Returns the *total*
    (not per-step) log-likelihood — ELBO and responsibilities need
    sequence-level scores."""
    out = np.empty(len(encoded), dtype=float)
    for i, X in enumerate(encoded):
        if X.shape[0] == 0:
            out[i] = -1e6
            continue
        try:
            out[i] = float(model.score(X))
        except Exception:                              # noqa: BLE001
            out[i] = -1e6
    return out


# ── VB-EM core ───────────────────────────────────────────────────────────


def _fit_mixture_for_K(encoded: Sequence[np.ndarray],
                       lengths: List[int],
                       alphabet: int,
                       K: int,
                       *,
                       seed: int = 0,
                       ) -> Optional[Tuple[List[Any], np.ndarray, np.ndarray, float, int]]:
    """One VB-EM run at fixed K from a fixed seed. Returns
    ``(hmms, alpha_post, responsibilities, elbo, n_iter)`` or None on
    catastrophic failure. The caller wraps this in restarts."""
    N = len(encoded)
    if N == 0 or K < 1:
        return None

    rng = np.random.RandomState(seed)

    # Initial soft assignment: random Dirichlet draws, biased mildly
    # toward sequence length so empty/short trajectories don't
    # dominate any single regime by accident.
    init = rng.dirichlet(np.ones(K) * 1.5, size=N)
    r = init / init.sum(axis=1, keepdims=True)

    alpha_post = np.full(K, DIRICHLET_PRIOR) + r.sum(axis=0)
    prev_elbo = -np.inf
    hmms: List[Optional[Any]] = [None] * K
    elbo = -np.inf

    for it in range(MAX_VB_ITER):
        # ── M-step: refit each regime's HMM on its hard-assigned
        # trajectories. We use hard EM for the HMM refit because
        # hmmlearn's Baum-Welch does not accept per-sample weights;
        # the soft responsibilities are still used in the E-step,
        # ELBO, and final regime tagging. This is a standard
        # pragmatic compromise for mixture-of-HMMs (Bilmes 1998).
        labels = r.argmax(axis=1)
        new_hmms: List[Optional[Any]] = []
        for k in range(K):
            members = [i for i in range(N) if labels[i] == k]
            if not members:
                new_hmms.append(None)
                continue
            Xs = [encoded[i] for i in members]
            X_cat = np.vstack(Xs) if Xs else np.empty((0, 1), dtype=int)
            L_cat = [encoded[i].shape[0] for i in members]
            n_states = max(1, min(HMM_STATES_PER_REGIME, alphabet))
            model = _fit_single_hmm(
                X_cat, L_cat, alphabet, n_states,
                random_state=seed * 100 + k * 7 + it,
            )
            new_hmms.append(model)
        hmms = new_hmms

        # ── E-step: responsibilities.
        # log r_{n,k} ∝ E[log π_k] + log p(x_n | HMM_k)
        E_log_pi = digamma(alpha_post) - digamma(alpha_post.sum())
        log_lik = np.full((N, K), -1e6, dtype=float)
        for k, hmm in enumerate(hmms):
            if hmm is None:
                continue
            log_lik[:, k] = _hmm_logL_per_trajectory(hmm, encoded)

        # The responsibility uses the full sequence log-likelihood —
        # this is the standard VB formulation. An earlier draft
        # length-normalised log_lik to defend against one very long
        # trajectory dominating a regime, but that flattens the
        # inter-regime signal when trajectories are similar lengths
        # (the corpus we care about) and kills separation. Clip to a
        # finite range so degenerate -inf scores from failed sub-fits
        # don't produce NaN responsibilities downstream.
        log_lik_safe = np.clip(log_lik, -1e6, 1e6)
        log_r = E_log_pi[None, :] + log_lik_safe
        log_r_norm = log_r - logsumexp(log_r, axis=1, keepdims=True)
        r = np.exp(log_r_norm)
        r = np.clip(r, 1e-12, 1.0)
        r = r / r.sum(axis=1, keepdims=True)

        alpha_post = np.full(K, DIRICHLET_PRIOR) + r.sum(axis=0)

        # ── ELBO. Drop constants (priors on HMM params); we use the
        # ELBO only for K-selection and convergence, not as a
        # calibrated marginal likelihood.
        E_log_pi_new = digamma(alpha_post) - digamma(alpha_post.sum())
        elbo_data = float(np.sum(r * log_lik_safe))
        elbo_pi = float(np.sum(r * E_log_pi_new[None, :]))
        # entropy of q(z) — minus because ELBO subtracts log q
        with np.errstate(divide="ignore", invalid="ignore"):
            elbo_qz = -float(np.sum(r * np.log(np.where(r > 0, r, 1.0))))
        elbo = elbo_data + elbo_pi + elbo_qz

        if abs(elbo - prev_elbo) < ELBO_TOL:
            return hmms, alpha_post, r, elbo, it + 1
        prev_elbo = elbo

    return hmms, alpha_post, r, elbo, MAX_VB_ITER


def _try_fit_with_restarts(encoded: Sequence[np.ndarray],
                           lengths: List[int],
                           alphabet: int,
                           K: int,
                           ) -> Optional[Tuple[List[Any], np.ndarray, np.ndarray, float, int]]:
    """N_RESTARTS independent VB-EM runs; keep the one with the
    highest ELBO. Restarts are the §6 mitigation against
    'VB local minima'."""
    best: Optional[Tuple[List[Any], np.ndarray, np.ndarray, float, int]] = None
    for r_idx in range(N_RESTARTS):
        result = _fit_mixture_for_K(
            encoded, lengths, alphabet, K, seed=42 + r_idx * 13,
        )
        if result is None:
            continue
        if best is None or result[3] > best[3]:        # higher ELBO wins
            best = result
    return best


# ── Top-level per-service fit ────────────────────────────────────────────


def fit_regime_model_for_service(
        trajectories: Sequence[Trajectory],
        *,
        K_max: int = K_MAX,
        ) -> Optional[Tuple[RegimeModel, List[TrajectoryRegimeAssignment]]]:
    """Fit a mixture-of-HMMs for one service. Returns the model plus
    the per-trajectory assignments, or None if the service is too
    small to support even K=1.

    K selection rule: sweep K=1..K_max, drop any K whose smallest
    regime claims fewer than ``MIN_TRAJ_PER_REGIME`` trajectories,
    return the K with the highest ELBO. ELBO is comparable across K
    because the Dirichlet prior penalises larger K through the
    α-spread term.
    """
    if not _OK:
        raise ImportError("hmmlearn + numpy + scipy required for L8. "
                          "Install via `pip install -e .[mining]`.")
    if not trajectories or len(trajectories) < MIN_TRAJ_PER_SERVICE:
        return None

    encoding, alphabet = _encode(trajectories)
    if alphabet < 2:
        return None

    encoded = [_encode_trajectory(t, encoding) for t in trajectories]
    lengths = [enc.shape[0] for enc in encoded]
    if sum(lengths) < MIN_HITS_FOR_HMM:
        return None

    best_payload: Optional[Tuple[int, Tuple[List[Any], np.ndarray, np.ndarray, float, int]]] = None
    for K in range(1, K_max + 1):
        # K=1 is the v1 baseline — always try it so we don't regress.
        result = _try_fit_with_restarts(encoded, lengths, alphabet, K)
        if result is None:
            continue
        hmms, alpha_post, r, elbo, n_iter = result
        # Reject K if any HMM didn't fit (None) or any regime is
        # under-populated.
        counts = r.argmax(axis=1)
        sizes = [int((counts == k).sum()) for k in range(K)]
        if any(h is None for h in hmms):
            continue
        if K > 1 and min(sizes) < MIN_TRAJ_PER_REGIME:
            continue
        if best_payload is None or elbo > best_payload[1][3]:
            best_payload = (K, result)

    if best_payload is None:
        # Fall back to forced K=1: a single-regime mixture is just a
        # plain CategoricalHMM, useful as a defensive default so the
        # downstream pipeline never crashes for a service that
        # technically passed the volume gate.
        result = _try_fit_with_restarts(encoded, lengths, alphabet, 1)
        if result is None:
            return None
        best_payload = (1, result)

    K, (hmms, alpha_post, r, elbo, n_iter) = best_payload

    # Per-regime thresholds: 5th percentile of per-step logL among
    # the trajectories that voted for this regime. Anomaly scoring
    # later compares trajectory logL to *its own regime's* threshold,
    # which is the whole point of L8.
    regime_objs: List[RegimeHMM] = []
    counts = r.argmax(axis=1)
    for k in range(K):
        members = [i for i in range(len(encoded)) if counts[i] == k]
        per_step = []
        for i in members:
            X = encoded[i]
            if X.shape[0] == 0:
                continue
            try:
                per_step.append(hmms[k].score(X) / X.shape[0])
            except Exception:                          # noqa: BLE001
                continue
        threshold = float(np.percentile(per_step, 5.0)) if per_step else float("-inf")
        regime_objs.append(RegimeHMM(
            model=hmms[k],
            n_states=int(getattr(hmms[k], "n_components", HMM_STATES_PER_REGIME)),
            n_train_trajectories=len(members),
            per_step_threshold=threshold,
        ))

    model = RegimeModel(
        service=trajectories[0].service,
        n_regimes=K,
        alphabet_size=alphabet,
        encoding=dict(encoding),
        regimes=regime_objs,
        mixing_alpha=alpha_post.tolist(),
        elbo=elbo,
        n_iter=n_iter,
    )

    assignments = []
    for i, t in enumerate(trajectories):
        full = r[i].tolist()
        assignments.append(TrajectoryRegimeAssignment(
            trajectory_id=_trajectory_id(t),
            service=t.service, host=t.host,
            regime_id=int(np.argmax(r[i])),
            posterior=float(np.max(r[i])),
            full_posteriors=full,
        ))
    return model, assignments


def fit_regime_models(trajectories: Sequence[Trajectory], *,
                      K_max: int = K_MAX,
                      ) -> Tuple[Dict[str, RegimeModel],
                                  List[TrajectoryRegimeAssignment]]:
    """Per-service VB-EM. Services below the volume gate are skipped
    silently (consistent with v1 behaviour)."""
    by_service: Dict[str, List[Trajectory]] = defaultdict(list)
    for t in trajectories:
        by_service[t.service].append(t)
    models: Dict[str, RegimeModel] = {}
    assignments: List[TrajectoryRegimeAssignment] = []
    for svc, traj in by_service.items():
        result = fit_regime_model_for_service(traj, K_max=K_max)
        if result is None:
            continue
        m, a = result
        models[svc] = m
        assignments.extend(a)
    return models, assignments


# ── Persistence ──────────────────────────────────────────────────────────


def persist_regime_models(conn: sqlite3.Connection,
                          models: Dict[str, RegimeModel]) -> int:
    """Pickle each per-service ``RegimeModel`` into
    ``log_regime_models``. Idempotent on (service, fit_at) — the
    UNIQUE constraint there means a re-run inserts a new row with
    a fresh timestamp; the latest row wins for downstream lookups."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='log_regime_models'"
    ).fetchone()
    if not row:
        return 0
    n = 0
    for svc, m in models.items():
        blob = pickle.dumps(m, protocol=pickle.HIGHEST_PROTOCOL)
        conn.execute(
            "INSERT INTO log_regime_models (service, n_regimes, model_blob) "
            "VALUES (?, ?, ?)",
            (svc, m.n_regimes, blob),
        )
        n += 1
    conn.commit()
    return n


def persist_trajectory_regimes(conn: sqlite3.Connection,
                               assignments: Sequence[TrajectoryRegimeAssignment]
                               ) -> int:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='log_trajectory_regimes'"
    ).fetchone()
    if not row:
        return 0
    n = 0
    for a in assignments:
        conn.execute(
            "INSERT INTO log_trajectory_regimes "
            "(trajectory_id, regime_id, posterior) VALUES (?, ?, ?) "
            "ON CONFLICT(trajectory_id, regime_id) DO UPDATE SET "
            "  posterior = excluded.posterior",
            (a.trajectory_id, a.regime_id, a.posterior),
        )
        n += 1
    conn.commit()
    return n


def load_latest_regime_model(conn: sqlite3.Connection, service: str
                              ) -> Optional[RegimeModel]:
    """Return the most recent ``RegimeModel`` for `service`, or None."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='log_regime_models'"
    ).fetchone()
    if not row:
        return None
    r = conn.execute(
        "SELECT model_blob FROM log_regime_models "
        "WHERE service = ? ORDER BY id DESC LIMIT 1",
        (service,),
    ).fetchone()
    if not r:
        return None
    try:
        return pickle.loads(r[0])
    except Exception:                                  # noqa: BLE001
        return None


def get_trajectory_regime_tag(conn: sqlite3.Connection,
                              trajectory_id: str) -> Optional[Dict[str, Any]]:
    """Look up the regime assignment for a single trajectory id.
    Returns ``{'regime_id': int, 'posterior': float}`` or None."""
    row = conn.execute(
        "SELECT regime_id, posterior FROM log_trajectory_regimes "
        "WHERE trajectory_id = ? ORDER BY posterior DESC LIMIT 1",
        (trajectory_id,),
    ).fetchone()
    if not row:
        return None
    return {"regime_id": int(row[0]), "posterior": float(row[1])}


# ── Regime-aware anomaly scoring (replaces v1's single-HMM score) ────────


@dataclass
class RegimeAnomalyHit:
    service: str
    host: Optional[str]
    trajectory_id: str
    regime_id: int
    n_regimes: int                                     # for UI tagging
    per_step_logL: float
    threshold: float
    change_point_idx: int
    change_point_cluster_id: int
    confidence: float

    def regime_tag(self) -> str:
        return f"Regime {self.regime_id + 1} of {self.n_regimes}"


def score_regime_anomalies(
        trajectories: Sequence[Trajectory],
        models: Dict[str, RegimeModel],
        assignments: Sequence[TrajectoryRegimeAssignment],
        ) -> List[RegimeAnomalyHit]:
    """Per-trajectory anomaly score evaluated **under its assigned
    regime's HMM and threshold**. A trajectory that looks normal under
    its own regime does not flag, even if it would look anomalous
    under a different regime — this is the acceptance gate.
    """
    assign_index: Dict[str, TrajectoryRegimeAssignment] = {
        a.trajectory_id: a for a in assignments
    }
    hits: List[RegimeAnomalyHit] = []
    for t in trajectories:
        m = models.get(t.service)
        if m is None:
            continue
        a = assign_index.get(_trajectory_id(t))
        if a is None:
            continue
        regime = m.regimes[a.regime_id]
        encoded = _encode_trajectory(t, m.encoding)
        if encoded.shape[0] == 0:
            continue
        try:
            per_step = float(regime.model.score(encoded) / encoded.shape[0])
        except Exception:                              # noqa: BLE001
            continue
        if per_step >= regime.per_step_threshold:
            continue
        # Change point: cluster id whose isolated emission probability
        # under this regime is lowest. Robust fallback: the first id.
        change_idx = 0
        change_cid = t.cluster_ids[0]
        try:
            B = regime.model.emissionprob_                # n_states × alphabet
            obs_logp = []
            for i, cid in enumerate(t.cluster_ids):
                if cid not in m.encoding:
                    obs_logp.append(0.0)
                    continue
                col = m.encoding[cid]
                marg = B[:, col].max()
                obs_logp.append(math.log(max(1e-12, float(marg))))
            change_idx = int(np.argmin(obs_logp))
            change_cid = t.cluster_ids[change_idx]
        except Exception:                              # noqa: BLE001
            pass
        gap = regime.per_step_threshold - per_step
        # Confidence: bounded sigmoid of the gap. Calibrated confidence
        # is L10's problem; here we just want a monotone signal.
        confidence = float(1.0 / (1.0 + math.exp(-gap)))
        hits.append(RegimeAnomalyHit(
            service=t.service, host=t.host,
            trajectory_id=a.trajectory_id,
            regime_id=a.regime_id,
            n_regimes=m.n_regimes,
            per_step_logL=per_step,
            threshold=regime.per_step_threshold,
            change_point_idx=change_idx,
            change_point_cluster_id=change_cid,
            confidence=confidence,
        ))
    return hits


# ── Anomaly-proposal persistence (regime-aware) ──────────────────────────


def persist_regime_anomaly_proposals(conn: sqlite3.Connection,
                                     hits: Sequence[RegimeAnomalyHit]
                                     ) -> int:
    """Write each ``RegimeAnomalyHit`` as a LOG_EVENT proposal with the
    L8 regime tag attached. The shape mirrors v1's
    ``sequence_learner.persist_anomaly_proposals`` so downstream
    review code (``wizard.log_review``) keeps treating these as
    normal LOG_EVENT rows — only the ``regime_tag`` column is new.

    Idempotent on a deterministic ``proposal_id`` derived from
    ``(service, host, change_point_cluster_id, regime_id)``. The
    regime_id is part of the key so a trajectory that drifts to a
    new regime in a later run gets a fresh proposal rather than
    silently overwriting the old one.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ontology_evolution_proposals'"
    ).fetchone()
    if row is None:
        return 0

    # log_templates is created by `log_templates.ensure_schema`, not
    # by db/schema.sql. Skip the join when it's absent — proposals
    # still land, they just lose the template sample text.
    has_templates = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='log_templates'"
    ).fetchone() is not None
    cid_to_sample: Dict[int, Tuple[str, str]] = {}
    cid_to_template_id: Dict[int, int] = {}
    if has_templates:
        cid_to_sample = {
            r[0]: (r[1], r[2]) for r in conn.execute(
                "SELECT cluster_id, template, sample_line FROM log_templates "
                "WHERE merged_into IS NULL"
            )
        }
        cid_to_template_id = {
            r[0]: r[1] for r in conn.execute(
                "SELECT cluster_id, id FROM log_templates "
                "WHERE merged_into IS NULL"
            )
        }

    n = 0
    for h in hits:
        _, sample = cid_to_sample.get(h.change_point_cluster_id, ("", ""))
        tmpl_id = cid_to_template_id.get(h.change_point_cluster_id)
        regime_tag = h.regime_tag()
        title = (f"Anomalous {h.service} trajectory ending in "
                 f"template #{h.change_point_cluster_id} ({regime_tag})")
        deterministic = uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"regime-anomaly:{h.service}:{h.host or '-'}:"
            f"{h.change_point_cluster_id}:{h.regime_id}",
        )
        candidate_turtle = (
            f"# Regime-aware HMM anomaly ({regime_tag})\n"
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
            " source_log_path, regime_tag, regime_posterior) "
            "VALUES (?, 'LOG_EVENT', ?, ?, ?, 'HMM_SEQUENCE_ANOMALY', "
            " ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(proposal_id) DO UPDATE SET "
            "  confidence_score = excluded.confidence_score, "
            "  dim_consistency_risk = excluded.dim_consistency_risk, "
            "  evidence_sample = excluded.evidence_sample, "
            "  regime_tag = excluded.regime_tag, "
            "  regime_posterior = excluded.regime_posterior, "
            "  updated_at = datetime('now')",
            (str(deterministic), title, candidate_turtle, evidence_sparql,
             h.confidence, min(1.0, max(0.0, (h.threshold - h.per_step_logL) / 5.0)),
             tmpl_id, sample, "", regime_tag, 1.0),
        )
        n += 1
    conn.commit()
    return n


# ── Pipeline ─────────────────────────────────────────────────────────────


@dataclass
class RegimeReport:
    trajectories: int = 0
    services_fit: int = 0
    total_regimes: int = 0
    assignments_persisted: int = 0
    anomalies: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "trajectories":             self.trajectories,
            "services_fit":             self.services_fit,
            "total_regimes":            self.total_regimes,
            "assignments_persisted":    self.assignments_persisted,
            "anomalies":                self.anomalies,
            "duration_s":               round(self.duration_s, 3),
        }


def mine_regimes(extractions: Sequence[dict],
                 conn: sqlite3.Connection,
                 *,
                 K_max: int = K_MAX,
                 ) -> RegimeReport:
    """End-to-end L8 pipeline. Mirrors v1's :func:`mine_sequences`
    structure but persists regime models + per-trajectory tags
    instead of one HMM per service. Does **not** by itself write
    LOG_EVENT proposals — that wiring lives in `wizard/log_review.py`
    which already owns the proposal-store contract; the regime tag
    travels through `log_trajectory_regimes` for it to pick up.
    """
    started = time.perf_counter()
    trajectories = build_trajectories(extractions)
    models, assignments = fit_regime_models(trajectories, K_max=K_max)
    persist_regime_models(conn, models)
    persist_trajectory_regimes(conn, assignments)
    hits = score_regime_anomalies(trajectories, models, assignments)
    persist_regime_anomaly_proposals(conn, hits)
    duration = time.perf_counter() - started
    return RegimeReport(
        trajectories=len(trajectories),
        services_fit=len(models),
        total_regimes=sum(m.n_regimes for m in models.values()),
        assignments_persisted=len(assignments),
        anomalies=len(hits),
        duration_s=duration,
    )


__all__ = [
    # constants
    "K_MAX", "MAX_VB_ITER", "ELBO_TOL", "MIN_TRAJ_PER_REGIME",
    # data classes
    "RegimeHMM", "RegimeModel", "TrajectoryRegimeAssignment",
    "RegimeAnomalyHit", "RegimeReport",
    # API
    "fit_regime_model_for_service", "fit_regime_models",
    "persist_regime_models", "persist_trajectory_regimes",
    "persist_regime_anomaly_proposals",
    "load_latest_regime_model", "get_trajectory_regime_tag",
    "score_regime_anomalies", "mine_regimes",
]
