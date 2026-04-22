"""
consolidation_daemon.py — Workstream 1: Agentic Semantic Memory Layer
======================================================================
Background process that runs on a configurable schedule and applies three
memory consolidation strategies to keep the ObservationRecord graph lean
and auditable.

Consolidation strategies
------------------------
1. **Supersession** — When a MEASURED observation replaces an INFERRED one
   on the same entity/property, the INFERRED record is marked with
   ``prov:wasInvalidatedBy`` pointing to the MEASURED record IRI, and
   graph size is reduced.

2. **Temporal compression** — Aggregate point observations into summary
   statistics for periods older than a configurable threshold, then
   invalidate the constituent point records.

3. **Conflict escalation** — When two MEASURED observations contradict each
   other with equal confidence, raise a ``ConflictEvent`` record for human
   review.

Configuration: ``runtime/consolidation_config.json``

Usage
-----
Standalone (blocking, with schedule):
    python3 runtime/consolidation_daemon.py --db db/enterprise.db

One-shot (single run, exits):
    python3 runtime/consolidation_daemon.py --db db/enterprise.db --once

Dry-run (report only, no DB changes):
    python3 runtime/consolidation_daemon.py --db db/enterprise.db --once --dry-run

Programmatic:
    from runtime.consolidation_daemon import ConsolidationDaemon
    daemon = ConsolidationDaemon(db_path="db/enterprise.db")
    summary = daemon.run_once()
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from memory import AgentMemory

_DEFAULT_CONFIG = os.path.join(_HERE, "consolidation_config.json")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config(config_path: str) -> dict:
    """Load and return the consolidation configuration dict."""
    if not os.path.isfile(config_path):
        print(f"  WARN ConsolidationDaemon: config not found at {config_path}, using defaults")
        return {}
    with open(config_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _cron_seconds(cron_expr: str) -> int:
    """Return approximate seconds until the next fire time for simple cron exprs.

    Only handles ``"0 H * * *"`` (daily at hour H) and falls back to 86400s.
    """
    try:
        parts = cron_expr.strip().split()
        if len(parts) >= 2 and parts[2] == "*":
            hour = int(parts[1])
            now = datetime.now(timezone.utc)
            target = now.replace(hour=hour, minute=int(parts[0]), second=0, microsecond=0)
            if target <= now:
                target = target.replace(day=target.day + 1)
            return max(60, int((target - now).total_seconds()))
    except Exception:
        pass
    return 86400  # Default: 24 hours


# ─── Daemon class ─────────────────────────────────────────────────────────────

class ConsolidationDaemon:
    """Memory consolidation daemon for the Agentic Semantic Memory Layer.

    Runs three consolidation strategies (supersession, temporal compression,
    conflict escalation) on the ObservationRecord store according to the
    schedule in ``consolidation_config.json``.

    Args:
        db_path: Absolute path to the SQLite enterprise database.
        config_path: Path to ``consolidation_config.json``.
            Defaults to ``runtime/consolidation_config.json``.
    """

    def __init__(
        self,
        db_path: str,
        config_path: str = _DEFAULT_CONFIG,
    ) -> None:
        self._db_path    = db_path
        self._config     = _load_config(config_path)
        self._memory     = AgentMemory(db_path)
        self._log_path   = os.path.join(
            os.path.dirname(_HERE),
            self._config.get("log_path", "output/reports/consolidation_log.jsonl"),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def run_once(self, dry_run: Optional[bool] = None) -> Dict:
        """Execute one consolidation pass over all enabled strategies.

        Args:
            dry_run: If ``True``, compute without making DB changes.
                     Defaults to ``consolidation_config.json["dry_run_default"]``.

        Returns:
            A consolidation summary dict (same shape as
            :meth:`AgentMemory.consolidate`), augmented with per-strategy
            breakdowns.
        """
        cfg      = self._config
        dry_run  = dry_run if dry_run is not None else cfg.get("dry_run_default", False)
        strats   = cfg.get("strategies", {})

        # Strategy parameters
        sup_enabled  = strats.get("supersession", {}).get("enabled", True)
        sup_days     = strats.get("supersession", {}).get("older_than_days", 30)

        cmp_enabled  = strats.get("temporal_compression", {}).get("enabled", True)
        cmp_days     = strats.get("temporal_compression", {}).get("older_than_days", 90)

        esc_enabled  = strats.get("conflict_escalation", {}).get("enabled", True)

        started_at   = _utcnow()
        print(f"[{started_at}] ConsolidationDaemon: starting pass (dry_run={dry_run})")

        size_before = self._memory._graph_size()

        superseded  = 0
        compressed  = 0
        conflicts   = 0

        if sup_enabled:
            from datetime import timedelta
            cutoff_sup = (
                datetime.now(timezone.utc) - timedelta(days=sup_days)
            ).isoformat()
            superseded = self._memory._supersede_inferred(cutoff_sup, dry_run)
            print(f"  [supersession]         marked {superseded} INFERRED records superseded")

        if cmp_enabled:
            from datetime import timedelta
            cutoff_cmp = (
                datetime.now(timezone.utc) - timedelta(days=cmp_days)
            ).isoformat()
            compressed = self._memory._compress_old_observations(cutoff_cmp, dry_run)
            print(f"  [temporal_compression] compressed {compressed} point observations")

        if esc_enabled:
            conflicts = self._memory._escalate_conflicts(dry_run)
            print(f"  [conflict_escalation]  raised {conflicts} ConflictEvent records")

        size_after = self._memory._graph_size()
        reduction  = 0.0
        if size_before > 0:
            reduction = round((size_before - size_after) / size_before * 100, 1)

        # Alert if graph exceeds threshold
        alert_threshold = cfg.get("graph_size_alert_threshold", 100_000)
        if size_after > alert_threshold:
            print(
                f"  ALERT: graph size {size_after} exceeds threshold {alert_threshold}. "
                "Consider adjusting retention settings."
            )

        summary = {
            "run_started_at":      started_at,
            "run_completed_at":    _utcnow(),
            "dry_run":             dry_run,
            "graph_size_before":   size_before,
            "graph_size_after":    size_after,
            "reduction_pct":       reduction,
            "strategies": {
                "supersession":         {"enabled": sup_enabled, "count": superseded},
                "temporal_compression": {"enabled": cmp_enabled, "count": compressed},
                "conflict_escalation":  {"enabled": esc_enabled, "count": conflicts},
            },
            "totals": {
                "superseded_count": superseded,
                "compressed_count": compressed,
                "conflicts_raised":  conflicts,
            },
        }

        self._append_log(summary)
        print(
            f"[{summary['run_completed_at']}] ConsolidationDaemon: done. "
            f"graph {size_before}→{size_after} ({reduction}% reduction)"
        )
        return summary

    def run_scheduled(self) -> None:
        """Run the daemon on its configured schedule (blocking loop).

        Reads the cron expression from ``consolidation_config.json`` and
        sleeps between runs.  Run with ``--once`` for a single-shot pass.
        """
        schedule_cfg = self._config.get("schedule", {})
        enabled      = schedule_cfg.get("enabled", True)
        cron_expr    = schedule_cfg.get("cron", "0 2 * * *")

        if not enabled:
            print("ConsolidationDaemon: scheduling disabled in config. Exiting.")
            return

        print(
            f"ConsolidationDaemon: starting scheduled mode "
            f"(cron='{cron_expr}'). Press Ctrl+C to stop."
        )

        while True:
            self.run_once()
            wait_secs = _cron_seconds(cron_expr)
            next_run  = _utcnow()
            print(
                f"ConsolidationDaemon: next run in {wait_secs}s "
                f"(approx {wait_secs // 3600}h {(wait_secs % 3600) // 60}m)"
            )
            try:
                time.sleep(wait_secs)
            except KeyboardInterrupt:
                print("\nConsolidationDaemon: stopped by user.")
                break

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    def _append_log(self, summary: dict) -> None:
        """Append a consolidation run summary to the JSONL log file."""
        try:
            os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(summary, default=str) + "\n")
        except Exception as exc:
            print(f"  WARN ConsolidationDaemon._append_log: {exc}")


# ─── CLI entry point ──────────────────────────────────────────────────────────

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Memory consolidation daemon — Workstream 1: Agentic Semantic Memory"
    )
    parser.add_argument(
        "--db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite enterprise database",
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        metavar="PATH",
        help="Path to consolidation_config.json",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single consolidation pass and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be done but make no DB changes",
    )
    args = parser.parse_args()

    daemon = ConsolidationDaemon(db_path=args.db, config_path=args.config)

    if args.once:
        summary = daemon.run_once(dry_run=args.dry_run)
        print(json.dumps(summary, indent=2, default=str))
    else:
        daemon.run_scheduled()


if __name__ == "__main__":
    _cli()
