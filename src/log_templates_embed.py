"""
log_templates_embed.py — Phase L12
──────────────────────────────────
Probabilistic PCA over template-feature vectors.

Why this exists
───────────────
Drain's similarity threshold (``sim_th=0.4``) is one knob: too tight
and we get review fatigue from near-duplicate templates; too loose
and structurally distinct events collapse together. The dev plan
asked for a *posterior* over template count rather than a hard knob.

PCA over a bag-of-tokens representation of each template gives us
two things:

1. A small **embedding** (~8-16 components) over which we can compute
   pairwise distance — templates that are mostly duplicates with
   small token-level differences sit close together.
2. A 2D projection for the wizard UI: a small scatter that lights up
   the merge-candidate pairs (within distance δ in the full-dim
   embedding) so the engineer can confirm or dismiss them.

Probabilistic PCA (Bishop §12.2) extends classical PCA with a
Gaussian noise model. For the merge-candidate use case, the
noise variance estimate ``σ²`` tells us when distances aren't
meaningful (high noise → ignore). We expose it but the consumer
mostly cares about the projection + distance, which is what we
return.

Implementation
──────────────
- Bag-of-tokens: split the Drain template on whitespace / punctuation,
  drop the ``<*>`` placeholder and any single-character tokens, then
  let scikit-learn's ``CountVectorizer`` deal with stop tokens via
  built-in English stoplist (logs are mostly English keywords).
- ``sklearn.decomposition.PCA`` for the fit. PCA's first ``k``
  components are the maximum-likelihood pPCA solution up to rotation
  — fine for visualisation and distance, and avoids re-implementing
  EM. We expose ``noise_variance_`` as the standard pPCA σ² estimate
  for callers that want to know.
- Distance: Euclidean on the L2-normalised embedding. The
  L2-normalisation turns it into the chord distance equivalent of
  cosine similarity, which is what we actually care about (token
  frequency profile shape, not absolute mass).

Public API
──────────
    e = TemplateEmbedder(n_components=12).fit(conn)
    vec = e.embed(template_id)            # full-dim embedding
    x, y = e.project_2d(template_id)
    pairs = e.suggest_merges(threshold=0.25)
    payload = e.viz_payload()             # JSON-serialisable for UI
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import numpy as np
    _NP_OK = True
except ImportError:                                  # pragma: no cover
    _NP_OK = False

try:
    from sklearn.decomposition import PCA
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.preprocessing import normalize
    _SK_OK = True
except ImportError:                                  # pragma: no cover
    _SK_OK = False


# Defaults
DEFAULT_N_COMPONENTS = 12              # for merge-candidate distance
DEFAULT_N_VIZ = 2                      # for the scatter
DEFAULT_MERGE_THRESHOLD = 0.25         # L2-norm chord distance
MIN_TEMPLATES = 4                      # below this, pPCA is not informative
# Tokens we strip from template text before vectorising.
_PLACEHOLDER_PATTERNS = [
    re.compile(r"<\*>"),               # Drain placeholder
    re.compile(r"\{[^}]*\}"),          # f-string-like wildcards
]
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")   # ≥2-char tokens


def _normalise(template_text: str) -> str:
    """Strip Drain placeholders and lowercase. The result feeds
    ``CountVectorizer``'s tokeniser unchanged."""
    s = template_text or ""
    for pat in _PLACEHOLDER_PATTERNS:
        s = pat.sub(" ", s)
    return s.lower().strip()


def _tokenise(template_text: str) -> List[str]:
    """Public-ish tokeniser: used in tests, also wired into the
    vectoriser. Keeps tokens ≥ 2 chars, drops pure numeric and
    placeholder-derived noise."""
    return _TOKEN_RE.findall(_normalise(template_text))


# ── Dataclasses ──────────────────────────────────────────────────────────


@dataclass
class MergeCandidate:
    template_id_a: int
    template_id_b: int
    cluster_id_a: int
    cluster_id_b: int
    text_a: str
    text_b: str
    distance: float                    # L2 chord distance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id_a": self.template_id_a,
            "template_id_b": self.template_id_b,
            "cluster_id_a": self.cluster_id_a,
            "cluster_id_b": self.cluster_id_b,
            "text_a": self.text_a, "text_b": self.text_b,
            "distance": self.distance,
        }


@dataclass
class TemplateEmbedderState:
    """Persistent state of a fitted embedder. Set after ``fit``."""
    template_ids: List[int] = field(default_factory=list)
    cluster_ids: List[int] = field(default_factory=list)
    texts: List[str] = field(default_factory=list)
    embeddings: "np.ndarray" = field(default_factory=lambda: np.zeros((0, 0)))
    viz_2d: "np.ndarray" = field(default_factory=lambda: np.zeros((0, 0)))
    explained_variance_ratio: List[float] = field(default_factory=list)
    noise_variance: float = 0.0
    vocab_size: int = 0


# ── The embedder ─────────────────────────────────────────────────────────


class TemplateEmbedder:
    """Probabilistic PCA over the bag-of-tokens representation of
    Drain templates.

    Parameters
    ----------
    n_components : int
        Full embedding dimensionality for distance / merge candidates.
        Capped at min(n_components, n_templates - 1, vocab_size - 1).
    n_viz_components : int
        Dimensionality of the side-projection used for UI scatter
        (always 2 in practice, exposed for testing).
    merge_threshold : float
        Distance threshold for ``suggest_merges``.
    """

    def __init__(self,
                 n_components: int = DEFAULT_N_COMPONENTS,
                 n_viz_components: int = DEFAULT_N_VIZ,
                 merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
                 ) -> None:
        if n_components < 2:
            raise ValueError("n_components must be ≥ 2")
        self.n_components = int(n_components)
        self.n_viz_components = int(n_viz_components)
        self.merge_threshold = float(merge_threshold)
        self.state = TemplateEmbedderState()

    # ── Fit ─────────────────────────────────────────────────────────────

    def fit(self, conn: sqlite3.Connection) -> "TemplateEmbedder":
        """Pull all non-merged templates from ``log_templates``,
        tokenise, vectorise, fit pPCA. Returns ``self``.

        Raises ``RuntimeError`` if scikit-learn isn't installed or
        the corpus has fewer than ``MIN_TEMPLATES`` templates — both
        cases the UI handles by degrading gracefully (no scatter,
        no merge suggestions)."""
        if not (_NP_OK and _SK_OK):
            raise RuntimeError(
                "scikit-learn + numpy required for L12. "
                "Install via `pip install -e .[mining]`."
            )
        rows = list(conn.execute(
            "SELECT id, cluster_id, template "
            "FROM log_templates "
            "WHERE merged_into IS NULL "
            "ORDER BY id"
        ))
        if len(rows) < MIN_TEMPLATES:
            raise RuntimeError(
                f"need ≥ {MIN_TEMPLATES} templates to fit pPCA; "
                f"have {len(rows)}"
            )

        template_ids = [r[0] for r in rows]
        cluster_ids = [r[1] for r in rows]
        texts_raw = [r[2] or "" for r in rows]
        texts = [_normalise(t) for t in texts_raw]

        # Bag-of-tokens. We pre-tokenise with our own regex so we
        # control placeholder removal; CountVectorizer's tokeniser
        # would otherwise pick up Drain's <*> sequences.
        def _tok(text: str) -> List[str]:
            return _TOKEN_RE.findall(text)
        vec = CountVectorizer(
            tokenizer=_tok, lowercase=False,
            min_df=1, stop_words="english",
            token_pattern=None,
        )
        try:
            X = vec.fit_transform(texts)
        except ValueError as exc:
            raise RuntimeError(f"vectorisation failed: {exc}")
        if X.shape[1] == 0:
            raise RuntimeError("no usable tokens after stop-word removal")
        X_dense = X.toarray().astype(float)
        vocab_size = X_dense.shape[1]

        n_full = min(self.n_components, X_dense.shape[0] - 1, vocab_size - 1)
        n_full = max(2, n_full)
        n_viz = min(self.n_viz_components, n_full)

        pca_full = PCA(n_components=n_full)
        embeddings = pca_full.fit_transform(X_dense)
        pca_viz = PCA(n_components=n_viz)
        viz_2d = pca_viz.fit_transform(X_dense)

        # L2-normalise embeddings so distance is chord distance (≈ 1 - cosine).
        embeddings_norm = normalize(embeddings, axis=1)

        # pPCA noise variance estimate: residual variance after the
        # top-K eigenvalues. sklearn PCA exposes this as
        # ``noise_variance_`` when n_components < n_features. The
        # ``noise_variance_`` attribute may be 0 for full-rank fits
        # — that's fine, the consumer treats it as a sanity check.
        noise_var = float(getattr(pca_full, "noise_variance_", 0.0))

        self.state = TemplateEmbedderState(
            template_ids=template_ids,
            cluster_ids=cluster_ids,
            texts=texts_raw,
            embeddings=embeddings_norm,
            viz_2d=np.asarray(viz_2d, dtype=float),
            explained_variance_ratio=list(map(float, pca_full.explained_variance_ratio_)),
            noise_variance=noise_var,
            vocab_size=int(vocab_size),
        )
        return self

    # ── Inference ───────────────────────────────────────────────────────

    def _index(self, template_id: int) -> int:
        try:
            return self.state.template_ids.index(int(template_id))
        except ValueError:
            raise KeyError(f"template_id {template_id} not in fitted embedder")

    def embed(self, template_id: int) -> "np.ndarray":
        return self.state.embeddings[self._index(template_id)]

    def project_2d(self, template_id: int) -> Tuple[float, float]:
        v = self.state.viz_2d[self._index(template_id)]
        return float(v[0]), float(v[1]) if v.size > 1 else 0.0

    def distance(self, template_id_a: int, template_id_b: int) -> float:
        a = self.embed(template_id_a)
        b = self.embed(template_id_b)
        return float(np.linalg.norm(a - b))

    def suggest_merges(self, *, threshold: Optional[float] = None,
                       limit: int = 50) -> List[MergeCandidate]:
        """Return all distinct (a, b) template pairs with distance
        below ``threshold``, sorted by distance ascending.

        ``threshold`` defaults to ``self.merge_threshold``. ``limit``
        caps the returned list so the UI doesn't choke on a giant
        nearest-neighbour cloud."""
        if threshold is None:
            threshold = self.merge_threshold
        n = self.state.embeddings.shape[0]
        if n < 2:
            return []
        # Pairwise distance via broadcasting.
        diff = self.state.embeddings[:, None, :] - self.state.embeddings[None, :, :]
        dist = np.linalg.norm(diff, axis=2)
        cands: List[MergeCandidate] = []
        for i in range(n):
            for j in range(i + 1, n):
                d = float(dist[i, j])
                if d <= threshold:
                    cands.append(MergeCandidate(
                        template_id_a=int(self.state.template_ids[i]),
                        template_id_b=int(self.state.template_ids[j]),
                        cluster_id_a=int(self.state.cluster_ids[i]),
                        cluster_id_b=int(self.state.cluster_ids[j]),
                        text_a=self.state.texts[i],
                        text_b=self.state.texts[j],
                        distance=d,
                    ))
        cands.sort(key=lambda c: c.distance)
        return cands[:limit]

    def nearest_neighbours(self, template_id: int, k: int = 5
                           ) -> List[Tuple[int, float]]:
        """Top-k nearest templates by L2 chord distance, excluding
        the query template itself. Returns (template_id, distance)
        pairs sorted ascending."""
        idx = self._index(template_id)
        v = self.state.embeddings[idx]
        d = np.linalg.norm(self.state.embeddings - v, axis=1)
        order = np.argsort(d)
        out: List[Tuple[int, float]] = []
        for j in order:
            if int(j) == idx:
                continue
            out.append((int(self.state.template_ids[int(j)]), float(d[int(j)])))
            if len(out) >= k:
                break
        return out

    # ── UI payload ──────────────────────────────────────────────────────

    def viz_payload(self) -> Dict[str, Any]:
        """JSON-serialisable bundle for the wizard scatter card.
        Includes the per-template 2D points (with cluster id +
        truncated label) and the merge-candidate list."""
        s = self.state
        pts: List[Dict[str, Any]] = []
        for i, tid in enumerate(s.template_ids):
            text = s.texts[i] or ""
            pts.append({
                "template_id": int(tid),
                "cluster_id":  int(s.cluster_ids[i]),
                "label": text[:60],
                "x": float(s.viz_2d[i, 0]) if s.viz_2d.shape[1] > 0 else 0.0,
                "y": float(s.viz_2d[i, 1]) if s.viz_2d.shape[1] > 1 else 0.0,
            })
        merges = [c.to_dict() for c in self.suggest_merges()]
        return {
            "points": pts,
            "merges": merges,
            "explained_variance_ratio": list(s.explained_variance_ratio),
            "noise_variance": float(s.noise_variance),
            "vocab_size": int(s.vocab_size),
            "n_templates": len(s.template_ids),
        }


__all__ = [
    "TemplateEmbedder", "TemplateEmbedderState", "MergeCandidate",
    "DEFAULT_N_COMPONENTS", "DEFAULT_MERGE_THRESHOLD", "MIN_TEMPLATES",
    "_tokenise",
]
