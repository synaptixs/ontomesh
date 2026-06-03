"""T3.5 — Neural-with-attention sequence models.

Tests the numpy-only self-attention model + the attention-as-
audit-trail explanation API.

Acceptance gate (roadmap §3.T3.5, narrow framing):
- Per-token attention weights are surfaceable and interpretable
  (the audit-trail contract).
- The model is honest: it ships as a *parallel signal*, not a
  production HMM replacement. Tests verify the API but make NO
  claim about anomaly-detection accuracy vs L8.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


from sequence_learner_neural import (                                # noqa: E402
    AttentionExplanation, SelfAttentionSequenceModel,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _repeat_corpus(vocab=8, length=12, n_sequences=20):
    """Repeating pattern — the model should learn that token X
    always follows token X-1 (mod vocab)."""
    return [[(i + j) % vocab for i in range(length)]
            for j in range(n_sequences)]


# ── Initialisation + fit ─────────────────────────────────────────────


def test_fit_initialises_parameters():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    assert not model._fitted
    model.fit(_repeat_corpus(), epochs=2)
    assert model._fitted
    # Embedding matrix populated.
    assert model._E.shape == (8, 16)


def test_fit_with_empty_corpus_raises():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16)
    with pytest.raises(ValueError):
        model.fit([])


def test_fit_clips_oversized_tokens_to_vocab():
    model = SelfAttentionSequenceModel(vocab_size=4, dim=8)
    model.fit([[0, 1, 999, 2]], epochs=2)
    # Should not raise / not error on out-of-vocab tokens.
    assert model._fitted


def test_fit_loss_decreases_or_stays_finite():
    """Training should not produce NaN loss or diverge."""
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=10)
    assert np.isfinite(model.final_loss)


# ── Inference / explanation ──────────────────────────────────────────


def test_explain_raises_when_not_fitted():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16)
    with pytest.raises(RuntimeError):
        model.explain([0, 1, 2])


def test_explain_returns_attention_for_last_token_by_default():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=3)
    expl = model.explain([0, 1, 2, 3, 4])
    assert isinstance(expl, AttentionExplanation)
    assert expl.position == 4
    assert expl.token == 4


def test_explain_respects_explicit_position():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=3)
    expl = model.explain([0, 1, 2, 3, 4], position=2)
    assert expl.position == 2
    assert expl.token == 2


def test_explain_position_zero_returns_no_prior_tokens():
    """Position 0 has no past — attention list should be empty."""
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=2)
    expl = model.explain([3, 4, 5], position=0)
    assert expl.position == 0
    # Causal mask: only the position itself is in scope, and we
    # filter it out — so attended_positions is empty.
    assert expl.attended_positions == []


def test_explain_attention_weights_sum_to_one_over_prior_positions():
    """Acceptance gate: per-token attention is a *valid* distribution
    over prior tokens (softmax output, sums to ≤ 1 after we drop
    the self-attention weight)."""
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=3)
    expl = model.explain([0, 1, 2, 3, 4], position=4)
    total = sum(w for _, _, w in expl.attended_positions)
    # All 4 prior positions have non-zero weight; plus the self-
    # attention at position 4. Total over priors should be ≤ 1.0
    # (the remainder went to self).
    assert total <= 1.0 + 1e-6
    assert total > 0.5     # softmax should give most weight to priors


def test_top_k_returns_at_most_k_entries():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=2)
    expl = model.explain([0, 1, 2, 3, 4, 5])
    top3 = expl.top_k(k=3)
    assert len(top3) <= 3
    # Sorted in descending weight.
    weights = [w for _, _, w in top3]
    assert weights == sorted(weights, reverse=True)


def test_explanation_carries_predicted_next_token():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=3)
    expl = model.explain([0, 1, 2])
    assert 0 <= expl.predicted_next < 8
    # Log probability is negative (it's a log of a < 1 number).
    assert expl.predicted_logprob <= 0.0


# ── score() ──────────────────────────────────────────────────────────


def test_score_returns_finite_log_probability():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=3)
    s = model.score([0, 1, 2, 3])
    assert np.isfinite(s)
    assert s <= 0.0          # log probability


def test_score_raises_when_not_fitted():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16)
    with pytest.raises(RuntimeError):
        model.score([0, 1, 2])


def test_score_handles_short_sequences_gracefully():
    model = SelfAttentionSequenceModel(vocab_size=8, dim=16, seed=0)
    model.fit(_repeat_corpus(), epochs=2)
    # 0-length and 1-length sequences should return 0 (no next-token
    # predictions possible).
    assert model.score([]) == 0.0
    assert model.score([3]) == 0.0


# ── Honest framing: no production claim ──────────────────────────────


def test_module_docstring_marks_as_framework_prototype():
    """The module's docstring must call out the v3 roadmap
    constraint that T3.5 ships as a parallel signal, not a
    replacement for HMMs. Tests this explicitly so the framing
    can't drift away in a future refactor."""
    import sequence_learner_neural
    doc = sequence_learner_neural.__doc__ or ""
    # Either phrase signals the right framing.
    assert ("framework prototype" in doc.lower()
            or "parallel signal" in doc.lower()
            or "not a production replacement" in doc.lower()), (
        "module framing has drifted — T3.5 must remain explicit "
        "about not being a HMM replacement"
    )
