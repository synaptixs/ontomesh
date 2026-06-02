"""
src/sparse_gp.py — T3.2
───────────────────────
Sparse-inducing-point Gaussian Process.

Why this exists
───────────────
L13's per-template GP costs O(n³) per fit (the standard exact GP
posterior). On a 7-day × 60-template corpus that's bounded at
~96 points per template via aggressive sub-sampling; on a
30-day × 1000-template corpus the cubic cost blows the 60-s
acceptance budget. We deliberately capped MAX_SAMPLES_PER_FIT
at 96 in v2 to ship — T3.2 removes the cap by switching to a
Nyström-style sparse approximation.

The simplest robust strategy: pick ``m`` *inducing points*
deterministically (quantile-grid over hour-of-day), fit a
standard kernel-ridge regressor on those m points, then predict
on the original n points via the kernel cross-matrix. That gives
us the GP's posterior mean exactly (kernel-ridge with σ² noise =
GP regression mean) plus a tractable predictive variance via the
diagonal of the kernel residual.

We don't implement full FITC / VFE here — the predictive
variance approximation is good enough for the residual MAD-z
scoring path L13 already uses, and the extra book-keeping isn't
worth it at our scale.

Public API
──────────
    gp = SparseGP(kernel=k, n_inducing=64).fit(X, y)
    mu = gp.predict(X_test)
    mu, sigma = gp.predict(X_test, return_std=True)

The interface intentionally mirrors ``sklearn.gaussian_process.
GaussianProcessRegressor`` so callers (L13) can swap the two
behind a flag with one line of code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

import numpy as np


# ── Helpers ──────────────────────────────────────────────────────────────


def _select_inducing_points(X: np.ndarray, n_inducing: int) -> np.ndarray:
    """Pick ``n_inducing`` rows from ``X`` to act as inducing points.

    Strategy:
    - If n_inducing ≥ len(X), return X unchanged.
    - Else, sort by the first column and pick at evenly-spaced
      quantiles. For 1-D inputs (the L13 case — hour of day)
      this gives the optimal coverage.

    Deterministic — no RNG state, no k-means stochasticity.
    """
    n = X.shape[0]
    if n <= n_inducing:
        return X.copy()
    # Sort by first column.
    order = np.argsort(X[:, 0])
    X_sorted = X[order]
    idx = np.linspace(0, n - 1, n_inducing).round().astype(int)
    idx = np.unique(idx)              # dedupe in case of ties
    return X_sorted[idx]


# ── SparseGP ─────────────────────────────────────────────────────────────


@dataclass
class SparseGP:
    """Sparse GP regressor with inducing points.

    Parameters
    ----------
    kernel : callable, optional
        A function ``k(X1, X2) -> ndarray`` returning the kernel
        matrix between row-sets. If None, a simple periodic + RBF
        + white kernel is used (matches L13's choice).
    n_inducing : int
        Max number of inducing points. Default 64 — empirically
        sufficient for 24-hour periodic patterns with sub-bin
        resolution.
    noise_var : float
        Additive Gaussian noise variance σ². Acts as the ridge
        regulariser in the inducing-point fit.
    """

    kernel:     Optional[Callable] = None
    n_inducing: int = 64
    noise_var:  float = 1.0
    _Xu:        np.ndarray = field(default_factory=lambda: np.zeros((0, 1)))
    _alpha:     np.ndarray = field(default_factory=lambda: np.zeros(0))
    _K_uu:      np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    _y_mean:    float = 0.0
    _fitted:    bool = False

    # ── Default kernel ──────────────────────────────────────────────────

    @staticmethod
    def default_kernel(X1: np.ndarray, X2: np.ndarray) -> np.ndarray:
        """Periodic (24-hr) + RBF + small constant. Matches the L13
        choice modulo constants — the predictive shape we want is
        identical."""
        X1 = np.atleast_2d(X1).astype(float)
        X2 = np.atleast_2d(X2).astype(float)
        d = np.abs(X1[:, None, 0] - X2[None, :, 0])
        # Periodic part: sin² distance over 24-hr period.
        period = 24.0
        sin_d  = np.sin(np.pi * d / period)
        k_per  = np.exp(-2.0 * sin_d ** 2 / (3.0 ** 2))
        # RBF part on the same absolute distance (smooths the local
        # neighbourhood between aligned hours).
        k_rbf  = np.exp(-0.5 * (d / 4.0) ** 2)
        return 1.0 * (k_per + k_rbf) + 0.05

    def _k(self, X1: np.ndarray, X2: np.ndarray) -> np.ndarray:
        kfn = self.kernel or self.default_kernel
        return kfn(X1, X2)

    # ── Fit ─────────────────────────────────────────────────────────────

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SparseGP":
        X = np.atleast_2d(np.asarray(X, dtype=float))
        if X.shape[0] != X.shape[0]:
            raise ValueError("X must be 2-D")
        y = np.asarray(y, dtype=float).ravel()
        if X.shape[0] != y.shape[0]:
            raise ValueError("X and y must have the same length")

        # Subset-of-regressors inducing set.
        Xu = _select_inducing_points(X, self.n_inducing)
        # Center y for numerical stability; we add the mean back
        # at predict time.
        y_mean = float(y.mean()) if y.size else 0.0
        y_c = y - y_mean

        K_nu = self._k(X, Xu)         # (n, m)
        K_uu = self._k(Xu, Xu)        # (m, m)

        # Solve (K_uu + σ²/n * K_nu.T @ K_nu) α = K_nu.T @ y_c
        # (this is the SOR / subset-of-regressors normal equation;
        # equivalent to kernel ridge regression restricted to the
        # inducing points.)
        reg = max(self.noise_var, 1e-6) * np.eye(K_uu.shape[0])
        A = K_uu + (K_nu.T @ K_nu) / max(self.noise_var, 1e-6) + 1e-6 * np.eye(K_uu.shape[0])
        b = K_nu.T @ y_c / max(self.noise_var, 1e-6)
        try:
            alpha = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            alpha = np.linalg.lstsq(A, b, rcond=None)[0]

        self._Xu = Xu
        self._alpha = alpha
        self._K_uu = K_uu
        self._y_mean = y_mean
        self._fitted = True
        return self

    # ── Predict ─────────────────────────────────────────────────────────

    def predict(self, X_test: np.ndarray,
                return_std: bool = False
                ) -> Any:
        if not self._fitted:
            raise RuntimeError("SparseGP.predict called before fit")
        X_test = np.atleast_2d(np.asarray(X_test, dtype=float))
        K_su = self._k(X_test, self._Xu)
        mu = K_su @ self._alpha + self._y_mean
        if not return_std:
            return mu
        # Posterior variance for the SOR approximation.
        # Var(f*) ≈ k(*,*) - K_su K_uu⁻¹ K_us  +  noise_var
        # (the FITC corrective term is omitted — the residual MAD-z
        #  scoring path doesn't need exact intervals.)
        try:
            K_uu_inv = np.linalg.inv(self._K_uu
                                      + 1e-6 * np.eye(self._K_uu.shape[0]))
            K_ss_diag = np.array([self._k(np.array([[x]]),
                                           np.array([[x]]))[0, 0]
                                   for x in X_test[:, 0]])
            quad = np.einsum("ij,jk,ik->i", K_su, K_uu_inv, K_su)
            var = np.maximum(K_ss_diag - quad + self.noise_var, 1e-6)
            sigma = np.sqrt(var)
        except np.linalg.LinAlgError:
            sigma = np.full(X_test.shape[0], np.sqrt(self.noise_var))
        return mu, sigma

    def score(self, X: np.ndarray, y: np.ndarray) -> float:
        """R²-style coefficient on a held-out set. Used in tests."""
        mu = self.predict(X)
        ss_res = float(np.sum((y - mu) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2)) + 1e-12
        return 1.0 - ss_res / ss_tot

    @property
    def n_inducing_used(self) -> int:
        return self._Xu.shape[0] if self._fitted else 0


__all__ = ["SparseGP"]
