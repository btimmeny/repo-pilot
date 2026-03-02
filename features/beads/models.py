"""
Data models for the beads feature.

Bead and BeadStatus are the core domain objects for tracking
discrete units of work through the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BeadStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Bead:
    """A single tracked unit of work in the pipeline."""
    id: str
    name: str
    category: str
    status: BeadStatus = BeadStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    duration_sec: float | None = None
    input_summary: str = ""
    output_summary: str = ""
    error: str | None = None
    metadata: dict = field(default_factory=dict)
