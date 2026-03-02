"""
Pydantic models for the pipeline.

Note: Bead and BeadStatus have moved to features.beads.models.
They are re-exported here for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# Bead domain models — canonical home is features.beads.models
from features.beads.models import Bead, BeadStatus  # noqa: F401


class ImprovementCategory(str, Enum):
    FEATURES = "features"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    INTEGRATION = "integration"


class TestGroup(str, Enum):
    FEATURES = "features"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    INTEGRATION = "integration"


@dataclass
class Improvement:
    """A suggested code improvement."""
    id: str
    category: ImprovementCategory
    title: str
    description: str
    files_affected: list[str] = field(default_factory=list)
    priority: str = "medium"  # low, medium, high
    changes: list[dict] = field(default_factory=list)  # [{file, old, new}]


@dataclass
class ReviewResult:
    """Code review result with scoring."""
    overall_score: float  # 1-10
    scores: dict = field(default_factory=dict)  # {category: score}
    issues: list[dict] = field(default_factory=list)
    passed: bool = False
    summary: str = ""


@dataclass
class TestCase:
    """A single test case."""
    id: str
    group: TestGroup
    name: str
    description: str
    test_code: str
    file_path: str = ""


@dataclass
class TestResult:
    """Result of running a test suite."""
    group: TestGroup
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    output: str = ""


@dataclass
class PipelineRun:
    """Complete record of a pipeline execution."""
    run_id: str = ""
    target_repo: str = ""
    branch_name: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_sec: float = 0.0
    status: str = "pending"

    # Phase outputs
    repo_analysis: dict = field(default_factory=dict)
    improvements: list[dict] = field(default_factory=list)
    beads: list[dict] = field(default_factory=list)
    code_changes: list[dict] = field(default_factory=list)
    review: dict = field(default_factory=dict)
    tests_generated: list[dict] = field(default_factory=list)
    test_results: list[dict] = field(default_factory=dict)
    merge_result: dict = field(default_factory=dict)
    docs_updated: list[str] = field(default_factory=list)

    # Final
    log_file: str = ""
    error: str | None = None
