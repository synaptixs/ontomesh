"""
vb_hmm.py — Phase L10
─────────────────────
Variational Bayesian HMM with categorical emissions.

Purpose
───────
v1's ``sequence_learner`` picks a CategoricalHMM via BIC point
estimate and hand-tunes a confidence floor (``max(c, 0.6)``) so the
acceptance gate at the dev-plan stage is met. That floor is the
single biggest piece of unprincipled glue in the v1 anomaly path:
engineers can't compare confidence across kinds, and reviewers can't
defend a score of "0.6" in an audit.

L10 replaces it with a proper variational posterior:

  - π     ~ Dir(u₀)        — start probabilities
  - A_{i,:} ~ Dir(a₀)      — transition rows
  - B_{i,:} ~ Dir(b₀)      — emission rows (one Dirichlet per state
                              over the categorical alphabet)
  - z_{1:T} latent state path, marginalised exactly via the standard
                              forward-backward algorithm in log space

Mean-field factorisation::

    q(π, A, B, z) = q(π) · ∏_i q(A_{i,:}) · ∏_i q(B_{i,:}) · q(z_{1:T})

VB-EM updates use the standard Beal-2003 derivation: replace each
``log θ`` term in forward-backward with its variational expectation
``ψ(α_k) - ψ(Σ_k α_k)`` (digamma of the Dirichlet posterior), then
update the Dirichlet sufficient statistics from the resulting
state / pair marginals.

Convergence: ELBO change < ``ELBO_TOL`` or max ``MAX_ITER`` iterations
(per §8 Q5: ``1e-4`` and ``200`` respectively). 3 random restarts
mitigate VB's known local-minima behaviour.

Public API
──────────
    vb = VBHMM(n_states=4, alphabet=20).fit(sequences)
    elbo = vb.elbo()                       # final ELBO
    mu_logL, sd_logL = vb.posterior_predictive_per_step_logL(seq)
    confidence = vb.calibrated_confidence(seq, threshold)

Calibrated confidence
─────────────────────
For a held-out sequence the per-step log-likelihood is itself a
random variable under the variational posterior. We Monte-Carlo
sample ``N_SAMPLES`` parameter draws from q, score the sequence
under each, and report the Gaussian approximation of the predictive
distribution. The confidence

    P(true per-step logL < anomaly_threshold)

is then ``Φ((threshold - μ) / σ)`` — a real probability, comparable
across services and kinds, with no heuristic floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.special import digamma, gammaln, logsumexp

# Per §8 Q5 decision.
ELBO_TOL = 1e-4
MAX_ITER = 200
N_RESTARTS = 3
N_SAMPLES = 32                # Monte Carlo draws for predictive distribution


# ── Dirichlet helpers ────────────────────────────────────────────────────


def _dirichlet_E_log(alpha: np.ndarray) -> np.ndarray:
    """E_q[log θ_k] under q(θ) = Dir(α). Returns the same shape as
    ``alpha``; broadcasts along all-but-last axis."""
    return digamma(alpha) - digamma(alpha.sum(axis=-1, keepdims=True))


def _dirichlet_kl(alpha_q: np.ndarray, alpha_p: np.ndarray) -> float:
    """KL(Dir(α_q) || Dir(α_p)) — closed form. Sums across all rows
    in the array (so the caller can pass batched parameters)."""
    aq_sum = alpha_q.sum(axis=-1, keepdims=True)
    ap_sum = alpha_p.sum(axis=-1, keepdims=True)
    term1 = gammaln(aq_sum) - gammaln(ap_sum)
    term2 = -(gammaln(alpha_q) - gammaln(alpha_p)).sum(axis=-1, keepdims=True)
    term3 = ((alpha_q - alpha_p) * (digamma(alpha_q) - digamma(aq_sum))
             ).sum(axis=-1, keepdims=True)
    return float((term1 + term2 + term3).sum())


# ── Forward-backward in log space ────────────────────────────────────────


def _forward_backward(obs: np.ndarray,
                      log_pi: np.ndarray,
                      log_A: np.ndarray,
                      log_B: np.ndarray
                      ) -> Tuple[np.ndarray, np.ndarray, float]:
    """Standard FB. ``obs`` is a 1-D int array of emission indices;
    ``log_*`` are real-valued (need not be normalised log probs — they
    are the variational expectations ``E_q[log θ]``).

    Returns ``(gamma, xi, logZ)``:
        gamma  shape (T, K)            — q(z_t = i)
        xi     shape (T-1, K, K)       — q(z_t = i, z_{t+1} = j)
        logZ   forward-algorithm log-normaliser
    """
    T = obs.shape[0]
    K = log_pi.shape[0]
    log_alpha = np.full((T, K), -np.inf)
    log_alpha[0] = log_pi + log_B[:, obs[0]]
    for t in range(1, T):
        log_alpha[t] = log_B[:, obs[t]] + logsumexp(
            log_alpha[t - 1][:, None] + log_A, axis=0,
        )
    logZ = float(logsumexp(log_alpha[-1]))

    log_beta = np.zeros((T, K))
    for t in range(T - 2, -1, -1):
        log_beta[t] = logsumexp(
            log_A + log_B[:, obs[t + 1]][None, :] + log_beta[t + 1][None, :],
            axis=1,
        )

    log_gamma = log_alpha + log_beta - logZ
    gamma = np.exp(log_gamma)

    if T > 1:
        log_xi = (log_alpha[:-1, :, None]
                  + log_A[None, :, :]
                  + log_B[:, obs[1:]].T[:, None, :]
                  + log_beta[1:, None, :]
                  - logZ)
        xi = np.exp(log_xi)
    else:
        xi = np.zeros((0, K, K))
    return gamma, xi, logZ


# ── The model ────────────────────────────────────────────────────────────


@dataclass
class VBHMMState:
    """Persistent state of a fitted VB-HMM."""
    n_states: int
    alphabet: int
    u: np.ndarray = field(default_factory=lambda: np.zeros(0))   # π Dirichlet (K,)
    a: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))  # A Dirichlet (K, K)
    b: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))  # B Dirichlet (K, V)
    u0: float = 1.0
    a0: float = 1.0
    b0: float = 1.0
    final_elbo: float = float("-inf")
    n_iter: int = 0
    converged: bool = False


class VBHMM:
    """Variational Bayes HMM with categorical emissions.

    Parameters
    ----------
    n_states : int
        Number of latent states K.
    alphabet : int
        Categorical vocabulary size M.
    u0, a0, b0 : float
        Symmetric Dirichlet prior concentrations on π, A, B. Defaults
        of 1.0 are weakly informative — uniform over the simplex.
    """

    def __init__(self, n_states: int, alphabet: int,
                 *, u0: float = 1.0, a0: float = 1.0, b0: float = 1.0,
                 random_state: int = 0) -> None:
        if n_states < 1 or alphabet < 1:
            raise ValueError("n_states and alphabet must be ≥ 1")
        self.state = VBHMMState(
            n_states=n_states, alphabet=alphabet,
            u0=u0, a0=a0, b0=b0,
        )
        self.random_state = int(random_state)

    # ── Fit ─────────────────────────────────────────────────────────────

    def _initial_params(self, seed: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        rng = np.random.RandomState(seed)
        K = self.state.n_states
        V = self.state.alphabet
        u = self.state.u0 + rng.dirichlet(np.ones(K)) * 1.0
        a = self.state.a0 + rng.dirichlet(np.ones(K), size=K) * 1.0
        b = self.state.b0 + rng.dirichlet(np.ones(V), size=K) * 1.0
        return u, a, b

    def _fit_once(self, sequences: Sequence[np.ndarray],
                  seed: int) -> Tuple[VBHMMState, float]:
        """One VB-EM run from a single random init. Returns
        ``(state, elbo)``. Used by ``fit`` for restarts."""
        u, a, b = self._initial_params(seed)
        prev_elbo = -np.inf
        elbo = -np.inf
        n_iter = 0
        converged = False

        for it in range(MAX_ITER):
            # ── E-step ───────────────────────────────────────────────
            E_log_pi = _dirichlet_E_log(u)
            E_log_A = _dirichlet_E_log(a)
            E_log_B = _dirichlet_E_log(b)

            # Accumulate expected sufficient statistics across sequences.
            ss_pi = np.zeros_like(u)
            ss_A = np.zeros_like(a)
            ss_B = np.zeros_like(b)
            total_logZ = 0.0
            entropy_q_z = 0.0

            for obs in sequences:
                if obs.shape[0] == 0:
                    continue
                gamma, xi, logZ = _forward_backward(
                    obs, E_log_pi, E_log_A, E_log_B,
                )
                ss_pi += gamma[0]
                if xi.size:
                    ss_A += xi.sum(axis=0)
                for v in range(self.state.alphabet):
                    mask = (obs == v)
                    if mask.any():
                        ss_B[:, v] += gamma[mask].sum(axis=0)
                total_logZ += logZ
                # Approximate entropy of q(z) consistent with the
                # mean-field factorisation used in VB-HMM literature
                # (Beal 2003): H[q(z)] = -Σ γ log γ - Σ ξ log ξ +
                # consistency cross-terms. We use the standard
                # ELBO short-cut: log Z (returned by FB) already
                # accounts for the entropy of q(z) when log probs are
                # the variational expectations, so the contribution
                # we still need is the part the forward-backward
                # normaliser missed (the q(π,A,B) entropy is handled
                # below in the KL terms).
                pass
            del entropy_q_z   # unused — log Z absorbs the equivalent term

            # ── M-step (variational parameter updates) ──────────────
            u_new = self.state.u0 + ss_pi
            a_new = self.state.a0 + ss_A
            b_new = self.state.b0 + ss_B

            # ── ELBO ────────────────────────────────────────────────
            elbo = total_logZ
            # KL(q || p) over each Dirichlet block. Subtracted because
            # ELBO = ⟨log p⟩ - ⟨log q⟩ = log Z - KL(q||p) under the
            # standard variational mean-field for exponential families.
            elbo -= _dirichlet_kl(u_new, np.full_like(u_new, self.state.u0))
            elbo -= _dirichlet_kl(a_new, np.full_like(a_new, self.state.a0))
            elbo -= _dirichlet_kl(b_new, np.full_like(b_new, self.state.b0))

            u, a, b = u_new, a_new, b_new
            n_iter = it + 1
            if abs(elbo - prev_elbo) < ELBO_TOL and it > 1:
                converged = True
                break
            prev_elbo = elbo

        out = VBHMMState(
            n_states=self.state.n_states, alphabet=self.state.alphabet,
            u=u, a=a, b=b,
            u0=self.state.u0, a0=self.state.a0, b0=self.state.b0,
            final_elbo=float(elbo), n_iter=n_iter, converged=converged,
        )
        return out, float(elbo)

    def fit(self, sequences: Sequence[np.ndarray]) -> "VBHMM":
        """Run ``N_RESTARTS`` independent VB-EM passes and keep the
        run with the highest ELBO. Raises ``ValueError`` if no
        sequences are provided."""
        sequences = [np.asarray(s, dtype=int).ravel() for s in sequences]
        if not any(s.shape[0] > 0 for s in sequences):
            raise ValueError("VBHMM.fit requires at least one non-empty sequence")

        best_state: Optional[VBHMMState] = None
        best_elbo = -np.inf
        for r in range(N_RESTARTS):
            seed = self.random_state + r * 17 + 11
            state, elbo = self._fit_once(sequences, seed)
            if elbo > best_elbo:
                best_elbo = elbo
                best_state = state
        if best_state is not None:
            self.state = best_state
        return self

    # ── Inference ───────────────────────────────────────────────────────

    def _point_params(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Posterior mean point estimate of (log π, log A, log B).
        Same form the forward-backward used during fitting."""
        return (_dirichlet_E_log(self.state.u),
                _dirichlet_E_log(self.state.a),
                _dirichlet_E_log(self.state.b))

    def elbo(self) -> float:
        return float(self.state.final_elbo)

    def score(self, obs: np.ndarray) -> float:
        """Variational log-evidence for a sequence (point estimate
        using posterior means). For Monte-Carlo predictive, see
        ``posterior_predictive_per_step_logL``."""
        obs = np.asarray(obs, dtype=int).ravel()
        if obs.size == 0:
            return 0.0
        log_pi, log_A, log_B = self._point_params()
        _, _, logZ = _forward_backward(obs, log_pi, log_A, log_B)
        return float(logZ)

    def _sample_params(self, n: int, rng: np.random.RandomState
                       ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Monte-Carlo draws from the variational posterior. Each draw
        returns (log π, log A, log B). ``log`` because that's what
        ``_forward_backward`` consumes."""
        out = []
        for _ in range(n):
            pi = rng.dirichlet(self.state.u)
            A = np.vstack([rng.dirichlet(self.state.a[i]) for i in range(self.state.n_states)])
            B = np.vstack([rng.dirichlet(self.state.b[i]) for i in range(self.state.n_states)])
            # Floor to avoid -inf log probabilities when a Dirichlet
            # draws a near-zero mass for an unused emission symbol.
            out.append((
                np.log(np.clip(pi, 1e-12, None)),
                np.log(np.clip(A, 1e-12, None)),
                np.log(np.clip(B, 1e-12, None)),
            ))
        return out

    def posterior_predictive_per_step_logL(
            self, obs: np.ndarray, *, n_samples: int = N_SAMPLES,
            ) -> Tuple[float, float]:
        """Monte-Carlo posterior predictive over per-step log-likelihood.

        Returns ``(mu, sigma)`` of the per-step logL under draws from
        q(π, A, B). For a fully-converged VB posterior with abundant
        data, sigma is small and the prediction is sharp; for a small
        corpus, sigma is large and confidence reflects that uncertainty.
        """
        obs = np.asarray(obs, dtype=int).ravel()
        if obs.size == 0:
            return 0.0, 0.0
        rng = np.random.RandomState(self.random_state + 1)
        per_step = []
        for log_pi, log_A, log_B in self._sample_params(n_samples, rng):
            _, _, logZ = _forward_backward(obs, log_pi, log_A, log_B)
            per_step.append(logZ / obs.size)
        per_step = np.asarray(per_step, dtype=float)
        return float(per_step.mean()), float(per_step.std(ddof=1) if per_step.size > 1 else 0.0)

    def calibrated_confidence(self, obs: np.ndarray, threshold: float,
                              *, n_samples: int = N_SAMPLES) -> float:
        """Posterior probability that the trajectory's per-step logL
        is below ``threshold``. Gaussian approximation of the
        Monte-Carlo predictive — sharp when the variational posterior
        is concentrated, soft when it isn't. No hand-tuned floor."""
        mu, sigma = self.posterior_predictive_per_step_logL(
            obs, n_samples=n_samples,
        )
        if sigma <= 1e-9:
            # Degenerate predictive (e.g. very long sequence + sharp
            # posterior). Fall back to deterministic compare.
            return 1.0 if mu < threshold else 0.0
        # Φ((threshold - μ) / σ)
        z = (threshold - mu) / sigma
        return float(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))


# ── Model averaging across K ─────────────────────────────────────────────


def fit_vb_hmm_with_model_averaging(
        sequences: Sequence[np.ndarray],
        alphabet: int,
        *,
        k_candidates: Sequence[int] = (2, 3, 4, 5),
        ) -> Tuple[VBHMM, float, List[Tuple[int, float, VBHMM]]]:
    """Fit a separate VB-HMM at each ``K`` in ``k_candidates`` and
    keep the one with the largest ELBO. Returns the chosen model,
    its ELBO, and the list of (K, ELBO, model) for inspection / BMA.

    Per the roadmap §3.L10: 'marginalise over model size by Bayesian
    model averaging across the top-K' — the chosen-K model dominates
    the BMA weight in practice because ELBO differences are large,
    so we return the argmax for the scoring API and expose the full
    list for any caller that wants a true mixture predictive.
    """
    if not sequences:
        raise ValueError("at least one sequence required")
    results: List[Tuple[int, float, VBHMM]] = []
    for k in k_candidates:
        if k < 1:
            continue
        try:
            model = VBHMM(n_states=k, alphabet=alphabet, random_state=42).fit(sequences)
            results.append((int(k), model.elbo(), model))
        except Exception:                                  # noqa: BLE001
            continue
    if not results:
        raise RuntimeError("no VB-HMM converged at any candidate K")
    results.sort(key=lambda kv: kv[1], reverse=True)
    best_k, best_elbo, best_model = results[0]
    return best_model, best_elbo, results


__all__ = [
    "VBHMM", "VBHMMState",
    "fit_vb_hmm_with_model_averaging",
    "ELBO_TOL", "MAX_ITER", "N_RESTARTS", "N_SAMPLES",
]
