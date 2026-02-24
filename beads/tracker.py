"""
Bead Tracker — tracks discrete units of work through the pipeline.

Each "bead" represents a single trackable task. Together they form a chain
that records the full execution history of a pipeline run.

Every state change is persisted to Postgres in real-time via beads.db,
so the audit trail survives crashes. If the DB is unavailable, the tracker
falls back to in-memory only (with a warning).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.schemas import Bead, BeadStatus

log = logging.getLogger(__name__)

# Try to import the DB layer; gracefully degrade if unavailable
_db_available = False
try:
    from beads import db as bead_db
    _db_available = True
except Exception:
    bead_db = None  # type: ignore


class BeadTracker:
    """Manages a chain of beads for a single pipeline run.

    Persists every state change to Postgres when available.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.beads: list[Bead] = []
        self._active: dict[str, float] = {}  # bead_id → start time

    def _persist(self, bead: Bead) -> None:
        """Persist the current bead state to Postgres."""
        if not _db_available or bead_db is None:
            return
        try:
            bead_dict = asdict(bead)
            # Convert BeadStatus enum to string value
            bead_dict["status"] = bead.status.value if hasattr(bead.status, "value") else str(bead.status)
            bead_db.upsert_bead(self.run_id, bead_dict)
        except Exception as e:
            log.warning("[BEAD] Failed to persist bead %s to DB: %s", bead.id, e)

    def create(self, name: str, category: str, input_summary: str = "") -> Bead:
        """Create a new bead and add it to the chain."""
        bead = Bead(
            id=f"bead-{uuid.uuid4().hex[:8]}",
            name=name,
            category=category,
            status=BeadStatus.PENDING,
            input_summary=input_summary,
        )
        self.beads.append(bead)
        log.info("[BEAD] Created: %s — %s (%s)", bead.id, name, category)
        self._persist(bead)
        return bead

    def start(self, bead: Bead) -> None:
        """Mark a bead as running."""
        bead.status = BeadStatus.RUNNING
        bead.started_at = datetime.now(timezone.utc).isoformat()
        self._active[bead.id] = time.monotonic()
        log.info("[BEAD] Started: %s — %s", bead.id, bead.name)
        self._persist(bead)

    def complete(self, bead: Bead, output_summary: str = "", metadata: dict | None = None) -> None:
        """Mark a bead as completed."""
        bead.status = BeadStatus.COMPLETED
        bead.completed_at = datetime.now(timezone.utc).isoformat()
        bead.output_summary = output_summary
        if metadata:
            bead.metadata.update(metadata)
        start = self._active.pop(bead.id, None)
        if start:
            bead.duration_sec = round(time.monotonic() - start, 2)
        log.info(
            "[BEAD] Completed: %s — %s (%.2fs)",
            bead.id, bead.name, bead.duration_sec or 0,
        )
        self._persist(bead)

    def fail(self, bead: Bead, error: str) -> None:
        """Mark a bead as failed."""
        bead.status = BeadStatus.FAILED
        bead.completed_at = datetime.now(timezone.utc).isoformat()
        bead.error = error
        start = self._active.pop(bead.id, None)
        if start:
            bead.duration_sec = round(time.monotonic() - start, 2)
        log.error("[BEAD] Failed: %s — %s: %s", bead.id, bead.name, error)
        self._persist(bead)

    def skip(self, bead: Bead, reason: str = "") -> None:
        """Mark a bead as skipped."""
        bead.status = BeadStatus.SKIPPED
        bead.output_summary = reason
        log.info("[BEAD] Skipped: %s — %s: %s", bead.id, bead.name, reason)
        self._persist(bead)

    def to_list(self) -> list[dict]:
        """Export all beads as a list of dicts."""
        return [asdict(b) for b in self.beads]

    def summary(self) -> dict:
        """Return a summary of the bead chain."""
        statuses = {}
        for b in self.beads:
            statuses[b.status.value] = statuses.get(b.status.value, 0) + 1
        total_duration = sum(b.duration_sec or 0 for b in self.beads)
        return {
            "run_id": self.run_id,
            "total_beads": len(self.beads),
            "statuses": statuses,
            "total_duration_sec": round(total_duration, 2),
        }
