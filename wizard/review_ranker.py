"""
wizard/review_ranker.py — Phase L9
──────────────────────────────────
Active-learning ranker for the Log Discovery review queue.

A small logistic-regression classifier trained on
``(features, decision)`` pairs harvested from the
``ontology_evolution_proposals`` table — ``APPROVED`` rows are positive
examples, ``REJECTED`` rows are negative. The fitted model rescores
``PENDING`` candidates so the queue sorts by what *this* reviewer tends
to approve rather than the static ``confidence × consequence`` heuristic.

Design contract
───────────────
- **Graceful fallback.** If scikit-learn isn't installed, if there is
  no fitted model on disk, or if there are fewer than ``MIN_DECISIONS``
  labelled rows, ``rerank`` is a no-op — callers (``list_candidates``)
  keep the SQL-default order. This lets L9 ship before L8 without
  breaking anything, and lets the ranker live alongside the v1 sort
  forever as a defensive fallback.
- **L8-independent.** The regime feature is read from
  ``proposal["regime_id"]`` if present; if the key is missing (because
  L8 hasn't shipped yet, or the row pre-dates L8), it is treated as
  ``NaN`` and imputed at fit time. When L8 lands, the next refit picks
  the feature up automatically.
- **Single pickle, simple persistence.** ``db/review_ranker.pkl``. The
  pickle is git-ignored; the meta table ``log_ranker_meta`` keeps the
  audit trail (n_decisions, AUC, fit_at).

PRML reference: §1.5 (decision theory + loss) and §4.3 (logistic
regression — the simplest model that gives calibrated probabilities
the queue can sort by).
"""

from __future__ import annotations

import math
import pickle
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Bare minimum decisions before we trust the fit. Below this the
# logistic regression overfits to a handful of rows and reranks worse
# than the SQL default. Roadmap §6 ("Cold-start ranker") calls for 20.
MIN_DECISIONS = 20

# Kinds we one-hot encode. Kept stable so a model fitted on one run
# is loadable on the next even after new kinds appear (unseen kinds
# encode to all-zero in the kind block — they get a neutral score).
_KINDS = ("LOG_EVENT", "LOG_ENTITY", "LOG_RELATIONSHIP", "LOG_CAUSAL_EDGE")

# Numeric feature names — order matters; persisted with the model.
_NUMERIC_FEATURES = (
    "confidence_score",
    "dim_evidence_volume",
    "dim_evidence_recency",
    "dim_cross_domain",
    "dim_consistency_risk",
    "title_token_count",
    "age_seconds",
    "regime_id",
)


# ── Feature extraction ───────────────────────────────────────────────────


def _safe_float(v: Any, default: float = float("nan")) -> float:
    try:
        if v is None:
            return default
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _age_seconds(created_at: Any) -> float:
    """Best-effort age in seconds. ``created_at`` is the SQLite
    ``datetime('now')`` default — an ISO-ish string. On parse failure
    returns NaN; the imputer absorbs it."""
    if not created_at:
        return float("nan")
    try:
        import datetime as _dt
        s = str(created_at).replace("T", " ").split(".")[0]
        dt = _dt.datetime.fromisoformat(s)
        now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
        return max(0.0, (now - dt).total_seconds())
    except Exception:                                      # noqa: BLE001
        return float("nan")


def extract_features(proposal: Dict[str, Any]) -> Dict[str, float]:
    """Pure function: proposal dict (as returned by ``list_candidates``)
    → feature dict. Missing or malformed inputs map to NaN; the
    ranker's imputer fills them at fit + score time.
    """
    title = proposal.get("title") or ""
    feats: Dict[str, float] = {
        "confidence_score":     _safe_float(proposal.get("confidence_score")),
        "dim_evidence_volume":  _safe_float(proposal.get("dim_evidence_volume")),
        "dim_evidence_recency": _safe_float(proposal.get("dim_evidence_recency")),
        "dim_cross_domain":     _safe_float(proposal.get("dim_cross_domain")),
        "dim_consistency_risk": _safe_float(proposal.get("dim_consistency_risk")),
        "title_token_count":    float(len(str(title).split())),
        "age_seconds":          _age_seconds(proposal.get("created_at")),
        # regime_id is the L8 hook. Absent today; populated once L8 ships.
        "regime_id":            _safe_float(proposal.get("regime_id")),
    }
    kind = str(proposal.get("kind") or "")
    for k in _KINDS:
        feats[f"kind_{k}"] = 1.0 if kind == k else 0.0
    return feats


def _vectorise(proposals: Sequence[Dict[str, Any]]) -> Tuple[List[List[float]], List[str]]:
    """Stable column ordering: numeric features first, then kind one-hots."""
    names = list(_NUMERIC_FEATURES) + [f"kind_{k}" for k in _KINDS]
    rows: List[List[float]] = []
    for p in proposals:
        f = extract_features(p)
        rows.append([f[n] for n in names])
    return rows, names


# ── Decision extraction from DB ──────────────────────────────────────────


def load_decisions(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Pull every APPROVED/REJECTED row from the proposal store as a
    list of dicts compatible with ``extract_features``. We attach the
    integer label as ``__label__`` (1=approved, 0=rejected) so the
    caller doesn't need a parallel list.
    """
    cur = conn.execute(
        "SELECT id, proposal_id, proposal_type, title, "
        "       confidence_score, dim_evidence_volume, dim_evidence_recency, "
        "       dim_cross_domain, dim_consistency_risk, status, created_at "
        "FROM ontology_evolution_proposals "
        "WHERE status IN ('APPROVED','REJECTED')"
    )
    out: List[Dict[str, Any]] = []
    for r in cur:
        out.append({
            "id": r[0], "proposal_id": r[1], "kind": r[2], "title": r[3],
            "confidence_score": r[4], "dim_evidence_volume": r[5],
            "dim_evidence_recency": r[6], "dim_cross_domain": r[7],
            "dim_consistency_risk": r[8], "status": r[9],
            "created_at": r[10],
            "__label__": 1 if r[9] == "APPROVED" else 0,
        })
    return out


# ── The ranker ───────────────────────────────────────────────────────────


@dataclass
class RankerMeta:
    n_decisions: int = 0
    n_approved: int = 0
    n_rejected: int = 0
    auc: Optional[float] = None
    fit_at: Optional[str] = None
    feature_names: List[str] = field(default_factory=list)


class ReviewRanker:
    """Logistic-regression ranker over proposal feature vectors.

    Public API
    ──────────
        rk = ReviewRanker()
        meta = rk.fit(decisions)             # decisions: list of dicts w/ __label__
        score = rk.score(proposal)           # float in [0, 1]
        ranked = rk.rerank(candidates)       # list, sorted desc by score
        rk.save(path);  ReviewRanker.load(path)
    """

    def __init__(self) -> None:
        self._pipeline = None
        self._feature_names: List[str] = []
        self.meta: RankerMeta = RankerMeta()

    # ── fit ─────────────────────────────────────────────────────────────

    def fit(self, decisions: Sequence[Dict[str, Any]]) -> RankerMeta:
        """Fit on a list of decision dicts (each carrying ``__label__``).

        Raises nothing — if there aren't enough rows, both labels aren't
        present, or sklearn is missing, returns a meta with
        ``n_decisions`` set but ``auc=None`` and ``self._pipeline=None``.
        Callers check ``is_fitted()`` before relying on scores.
        """
        import datetime as _dt
        n = len(decisions)
        n_pos = sum(1 for d in decisions if d.get("__label__") == 1)
        n_neg = n - n_pos
        self.meta = RankerMeta(
            n_decisions=n, n_approved=n_pos, n_rejected=n_neg,
            fit_at=_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
        )

        if n < MIN_DECISIONS or n_pos == 0 or n_neg == 0:
            self._pipeline = None
            return self.meta

        try:
            from sklearn.impute import SimpleImputer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            self._pipeline = None
            return self.meta

        X, names = _vectorise(decisions)
        y = [int(d["__label__"]) for d in decisions]
        self._feature_names = names
        self.meta.feature_names = names

        pipeline = Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(
                solver="liblinear", C=1.0, class_weight="balanced",
                max_iter=200, random_state=0,
            )),
        ])

        # CV AUC — only if we have enough samples for a meaningful split.
        auc = None
        if n >= 30 and n_pos >= 5 and n_neg >= 5:
            try:
                from sklearn.model_selection import cross_val_score
                k = min(5, n_pos, n_neg)
                if k >= 2:
                    scores = cross_val_score(
                        pipeline, X, y, cv=k, scoring="roc_auc",
                    )
                    auc = float(scores.mean())
            except Exception:                              # noqa: BLE001
                auc = None

        pipeline.fit(X, y)
        self._pipeline = pipeline
        self.meta.auc = auc
        return self.meta

    # ── inference ───────────────────────────────────────────────────────

    def is_fitted(self) -> bool:
        return self._pipeline is not None

    def score(self, proposal: Dict[str, Any]) -> float:
        """Posterior P(approved | features). Returns 0.5 if unfit so
        callers that mix ranker scores with other signals get a
        neutral contribution."""
        if not self.is_fitted():
            return 0.5
        X, _ = _vectorise([proposal])
        try:
            proba = self._pipeline.predict_proba(X)[0]
            return float(proba[1])  # class 1 = approved
        except Exception:                                  # noqa: BLE001
            return 0.5

    def rerank(self, candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort candidates by ranker score, descending. Each output
        row gets a ``ranker_score`` key so the UI can display it. If
        the ranker isn't fitted, returns the input unchanged (still
        copied to a list)."""
        if not self.is_fitted() or not candidates:
            return list(candidates)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        X, _ = _vectorise(candidates)
        try:
            probs = self._pipeline.predict_proba(X)[:, 1]
        except Exception:                                  # noqa: BLE001
            return list(candidates)
        for c, p in zip(candidates, probs):
            c2 = dict(c)
            c2["ranker_score"] = float(p)
            scored.append((float(p), c2))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [c for _, c in scored]

    # ── persistence ─────────────────────────────────────────────────────

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "pipeline": self._pipeline,
                    "feature_names": self._feature_names,
                    "meta": self.meta,
                    "schema_version": 1,
                },
                f,
            )

    @classmethod
    def load(cls, path: str) -> "ReviewRanker":
        """Load a ranker from disk. Raises FileNotFoundError if absent;
        returns a freshly-instantiated unfitted ranker if the pickle is
        unreadable (forward compatibility: pickle format changes don't
        crash the wizard, the queue just falls back to SQL order)."""
        rk = cls()
        with open(path, "rb") as f:
            try:
                blob = pickle.load(f)
            except Exception:                              # noqa: BLE001
                return rk
        rk._pipeline = blob.get("pipeline")
        rk._feature_names = blob.get("feature_names") or []
        rk.meta = blob.get("meta") or RankerMeta()
        return rk

    @classmethod
    def load_or_none(cls, path: str) -> Optional["ReviewRanker"]:
        """Forgiving load: returns None if the file isn't there. Use
        in hot paths where the model is optional."""
        if not Path(path).is_file():
            return None
        try:
            return cls.load(path)
        except Exception:                                  # noqa: BLE001
            return None


# ── DB-aware convenience: one-call refit-and-save ────────────────────────


def fit_from_conn(conn: sqlite3.Connection, model_path: str) -> Dict[str, Any]:
    """Pull APPROVED/REJECTED rows from `conn`, fit, persist. Returns
    a small dict summarising the result so the API endpoint and the
    UI badge can render without unpickling.

    Side effect: writes/updates a row in ``log_ranker_meta`` so the
    audit trail is queryable from SQL (useful for offline analysis
    when the pickle is gone)."""
    decisions = load_decisions(conn)
    rk = ReviewRanker()
    meta = rk.fit(decisions)
    rk.save(model_path)
    _record_meta(conn, meta, model_path)
    return {
        "fitted": rk.is_fitted(),
        "n_decisions": meta.n_decisions,
        "n_approved": meta.n_approved,
        "n_rejected": meta.n_rejected,
        "auc": meta.auc,
        "fit_at": meta.fit_at,
        "model_path": model_path,
    }


def _record_meta(conn: sqlite3.Connection, meta: RankerMeta, model_path: str) -> None:
    """Insert a row into ``log_ranker_meta`` if the table exists.
    No-ops if the migration hasn't been run yet — we never want a
    missing audit row to break a refit."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='log_ranker_meta'"
    ).fetchone()
    if not row:
        return
    conn.execute(
        "INSERT INTO log_ranker_meta "
        "(model_path, n_decisions, n_approved, n_rejected, auc, fit_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (model_path, meta.n_decisions, meta.n_approved, meta.n_rejected,
         meta.auc, meta.fit_at),
    )
    conn.commit()


def latest_meta(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """Most recent ``log_ranker_meta`` row, as a dict. None if the
    table doesn't exist or has no rows yet (the UI badge then renders
    'no model fitted yet')."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='log_ranker_meta'"
    ).fetchone()
    if not row:
        return None
    r = conn.execute(
        "SELECT model_path, n_decisions, n_approved, n_rejected, auc, fit_at "
        "FROM log_ranker_meta ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not r:
        return None
    return {
        "model_path": r[0], "n_decisions": r[1],
        "n_approved": r[2], "n_rejected": r[3],
        "auc": r[4], "fit_at": r[5],
    }


__all__ = [
    "MIN_DECISIONS", "ReviewRanker", "RankerMeta",
    "extract_features", "load_decisions",
    "fit_from_conn", "latest_meta",
]
