"""
src/template_library.py — T2.2
──────────────────────────────
Cross-corpus template library.

Mining the same kind of system twice (telecom client A then
telecom client B) shouldn't start from zero. T2.2 keeps a
signed, hashed library of template signatures the toolkit has
already seen; new corpora bootstrap their proposal queue by
matching against the library, inheriting prior approve / reject
decisions and ranker priors.

Privacy
-------
Signatures are deliberately one-way: a stable hash of the sorted
token set + the slot-type vector. **No raw log lines ever leave
the source corpus.** Federation (S3) propagates only the hash
and the aggregated decision counts; a downstream corpus that
matches a hash gets the *yes/no rate*, not the original logs.

Matching
--------
Two templates match when their ``tokens_hash`` is identical
(strict bag-of-tokens equality, post-stop-word and post-
placeholder removal). Looser similarity matching is opt-in via
``match_template(threshold)`` which uses the centroid + Jaccard
fallback — the strict path stays fast and exact for the common
case (telecom A's "User <*> logged in" exactly matches B's).

Public API
──────────
    sig = compute_signature(template, slot_types)
    lib = TemplateLibrary(conn)
    lib.register(signatures_iter, source="corpus-A")
    match = lib.find_match(signature)
    rep = lib.bootstrap_proposals(conn_new, extractions)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


# ── Defaults ─────────────────────────────────────────────────────────────


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")
_PLACEHOLDER_RE = re.compile(r"<\*>|\{[^}]*\}")


# ── Signature ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TemplateSignature:
    """One canonical signature. ``tokens_hash`` and ``slot_types``
    fully determine equality; ``signature_hash`` is the public id."""
    signature_hash: str          # 16-hex SHA-256 prefix
    tokens_hash:    str          # 16-hex over sorted-unique tokens
    slot_types:     Tuple[str, ...]
    n_tokens:       int
    n_slots:        int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "signature_hash": self.signature_hash,
            "tokens_hash":    self.tokens_hash,
            "slot_types":     list(self.slot_types),
            "n_tokens":       self.n_tokens,
            "n_slots":        self.n_slots,
        }


def compute_signature(template: str,
                      slot_types: Optional[Sequence[str]] = None
                      ) -> TemplateSignature:
    """Build a privacy-preserving signature for a template.

    ``template`` is the Drain template text (``<*>`` placeholders
    intact). ``slot_types`` is the list of typed slots from L1.5
    (e.g. ``["IRI", "UUID", "ENUM"]``); when None we leave it empty
    so the caller can match on token-shape alone.
    """
    text = _PLACEHOLDER_RE.sub(" ", template or "").lower()
    tokens = sorted(set(_TOKEN_RE.findall(text)))
    slot_t = tuple(s.upper() for s in (slot_types or []))
    tokens_hash = _hash16("tokens:" + ",".join(tokens))
    slots_hash  = _hash16("slots:" + ",".join(slot_t))
    sig = _hash16(f"{tokens_hash}|{slots_hash}")
    return TemplateSignature(
        signature_hash=sig,
        tokens_hash=tokens_hash,
        slot_types=slot_t,
        n_tokens=len(tokens),
        n_slots=len(slot_t),
    )


def _hash16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# ── Match results ────────────────────────────────────────────────────────


@dataclass
class LibraryMatch:
    """One match against the library. ``score`` is in [0, 1]; 1.0 for
    exact tokens-hash match, smaller for similarity-based matches."""
    signature_hash:     str
    n_approved:         int
    n_rejected:         int
    source_corpora:     List[str]
    score:              float = 1.0

    @property
    def approval_rate(self) -> float:
        total = self.n_approved + self.n_rejected
        return self.n_approved / total if total else 0.5

    def as_dict(self) -> Dict[str, Any]:
        return {
            "signature_hash":   self.signature_hash,
            "n_approved":       self.n_approved,
            "n_rejected":       self.n_rejected,
            "source_corpora":   list(self.source_corpora),
            "score":            self.score,
            "approval_rate":    self.approval_rate,
        }


@dataclass
class BootstrapReport:
    n_extractions:   int = 0
    n_unique_templates: int = 0
    n_matched:       int = 0
    n_auto_approved: int = 0
    n_skipped_rejected: int = 0
    library_size:    int = 0
    matches:         List[LibraryMatch] = field(default_factory=list)

    def reduction_rate(self) -> float:
        if self.n_unique_templates == 0:
            return 0.0
        return self.n_matched / self.n_unique_templates


# ── TemplateLibrary store ────────────────────────────────────────────────


class TemplateLibrary:
    """SQLite-backed library. The schema is created on first use
    if the v3 migration hasn't run yet — same pattern as the
    other Tier-2 stores."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        if self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='template_library'"
        ).fetchone() is None:
            from db.migrations.v3_template_library import migrate
            migrate(self.conn)

    # ── Registration ─────────────────────────────────────────────────────

    def register(self, signatures: Iterable[TemplateSignature],
                 *, source: str,
                 n_approved_each: int = 0,
                 n_rejected_each: int = 0) -> int:
        """Insert / update a batch of signatures. ``source`` is a
        free-text corpus identifier (the federation layer signs it
        upstream; this module just stores it). Returns the number of
        rows touched."""
        n = 0
        now = _now_iso()
        for sig in signatures:
            existing = self.conn.execute(
                "SELECT source_corpora, decisions_approved, decisions_rejected "
                "FROM template_library WHERE signature_hash = ?",
                (sig.signature_hash,),
            ).fetchone()
            sources = set()
            if existing:
                try:
                    sources = set(json.loads(existing[0] or "[]"))
                except Exception:                              # noqa: BLE001
                    sources = set()
                sources.add(source)
                self.conn.execute(
                    "UPDATE template_library SET "
                    " source_corpora = ?, "
                    " decisions_approved = decisions_approved + ?, "
                    " decisions_rejected = decisions_rejected + ?, "
                    " last_seen = ? "
                    "WHERE signature_hash = ?",
                    (json.dumps(sorted(sources)),
                     n_approved_each, n_rejected_each,
                     now, sig.signature_hash),
                )
            else:
                sources.add(source)
                self.conn.execute(
                    "INSERT INTO template_library "
                    "(signature_hash, tokens_hash, slot_types_json, "
                    " n_tokens, n_slots, decisions_approved, "
                    " decisions_rejected, source_corpora, "
                    " first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sig.signature_hash, sig.tokens_hash,
                     json.dumps(list(sig.slot_types)),
                     sig.n_tokens, sig.n_slots,
                     n_approved_each, n_rejected_each,
                     json.dumps(sorted(sources)),
                     now, now),
                )
            n += 1
        self.conn.commit()
        return n

    def record_decision(self, signature_hash: str,
                        *, approved: bool) -> None:
        """Append one decision to an existing library entry. No-op
        if the entry doesn't exist (we never auto-create on a single
        decision; registration is explicit)."""
        col = "decisions_approved" if approved else "decisions_rejected"
        self.conn.execute(
            f"UPDATE template_library SET {col} = {col} + 1, "
            f"last_seen = ? WHERE signature_hash = ?",
            (_now_iso(), signature_hash),
        )
        self.conn.commit()

    # ── Lookup ───────────────────────────────────────────────────────────

    def find_match(self, signature: TemplateSignature
                   ) -> Optional[LibraryMatch]:
        """Strict match by ``signature_hash``. Returns None when no
        library entry has the same hash."""
        row = self.conn.execute(
            "SELECT decisions_approved, decisions_rejected, source_corpora "
            "FROM template_library WHERE signature_hash = ?",
            (signature.signature_hash,),
        ).fetchone()
        if not row:
            return None
        try:
            sources = json.loads(row[2] or "[]")
        except Exception:                                      # noqa: BLE001
            sources = []
        return LibraryMatch(
            signature_hash=signature.signature_hash,
            n_approved=int(row[0] or 0),
            n_rejected=int(row[1] or 0),
            source_corpora=list(sources),
            score=1.0,
        )

    def size(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM template_library"
        ).fetchone()[0]

    # ── Bootstrap proposals on a new corpus ─────────────────────────────

    def bootstrap_proposals(self, target_conn: sqlite3.Connection,
                            extractions: Sequence[Dict[str, Any]],
                            *,
                            auto_approve_floor: int = 5,
                            auto_approve_ratio: float = 0.9,
                            auto_reject_floor:  int = 5,
                            auto_reject_ratio:  float = 0.1,
                            ) -> BootstrapReport:
        """For a new corpus's extractions, look up each template
        against the library. When a match has a strong historical
        approve / reject pattern, write the proposal directly to
        APPROVED / REJECTED status with ``reviewer_id='library:<hash>'``
        so the engineer reviews only the genuinely novel templates.

        Defaults are conservative — at least 5 historical decisions
        AND a 90 % / 10 % skew before automating. Lower the floors
        for fast bootstrapping on trusted corpora.
        """
        report = BootstrapReport(n_extractions=len(extractions))

        # Group extractions by cluster_id; we sign one template per cluster.
        by_cluster: Dict[int, List[Dict[str, Any]]] = {}
        for ex in extractions:
            cid = ex.get("cluster_id")
            if cid is None:
                continue
            by_cluster.setdefault(int(cid), []).append(ex)
        report.n_unique_templates = len(by_cluster)
        report.library_size = self.size()

        for cid, rows in by_cluster.items():
            template = rows[0].get("template") or rows[0].get("text") or ""
            slot_types = rows[0].get("slot_types") or []
            sig = compute_signature(template, slot_types)
            match = self.find_match(sig)
            if not match:
                continue
            report.n_matched += 1
            report.matches.append(match)
            decisions = match.n_approved + match.n_rejected

            if decisions < min(auto_approve_floor, auto_reject_floor):
                continue          # let the engineer decide

            if (decisions >= auto_approve_floor
                    and match.approval_rate >= auto_approve_ratio):
                self._auto_decide(target_conn, cid, sig,
                                   "APPROVED", match)
                report.n_auto_approved += 1
            elif (decisions >= auto_reject_floor
                    and match.approval_rate <= auto_reject_ratio):
                self._auto_decide(target_conn, cid, sig,
                                   "REJECTED", match)
                report.n_skipped_rejected += 1
        return report

    def _auto_decide(self, conn: sqlite3.Connection, cluster_id: int,
                     sig: TemplateSignature, status: str,
                     match: LibraryMatch) -> None:
        """Mark all PENDING proposals for ``cluster_id`` with the
        library-derived decision. Idempotent — re-running is a no-op
        on rows already at the target status."""
        cur = conn.execute(
            "SELECT proposal_id FROM ontology_evolution_proposals "
            "WHERE evidence_template_id = ? AND status = 'PENDING'",
            (cluster_id,),
        )
        note = (f"Library match {sig.signature_hash} "
                f"({match.n_approved}↑/{match.n_rejected}↓ across "
                f"{len(match.source_corpora)} corpora)")
        for (pid,) in cur:
            conn.execute(
                "UPDATE ontology_evolution_proposals SET "
                " status = ?, review_note = ?, "
                " reviewer_id = ?, reviewed_at = datetime('now'), "
                " updated_at = datetime('now') "
                "WHERE proposal_id = ?",
                (status, note, f"library:{sig.signature_hash}", pid),
            )
        conn.commit()


# ── Helpers ──────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(
        timespec="seconds",
    )


__all__ = [
    "TemplateSignature", "LibraryMatch", "BootstrapReport",
    "TemplateLibrary", "compute_signature",
]
