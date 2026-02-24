"""
Activity: Code Review — reviews all changes made by the pipeline and
produces a scored assessment.
"""

from __future__ import annotations

import logging
from pathlib import Path

from utils.llm import chat_json
from utils.repo_scanner import scan_repo, build_file_summary

log = logging.getLogger(__name__)


def review_changes(repo_path: str, applied_changes: list[dict]) -> dict:
    """
    Review all applied code changes and produce a scored assessment.

    Returns:
        {
            "overall_score": float (1-10),
            "scores": {"features": float, "security": float, "compliance": float, "integration": float},
            "issues": [{"severity": "...", "file": "...", "description": "..."}],
            "passed": bool,
            "summary": "..."
        }
    """
    log.info("Reviewing %d applied changes", len(applied_changes))
    scan = scan_repo(repo_path)

    # Build context of what changed
    changes_context = []
    for change in applied_changes:
        if change["status"] != "applied":
            continue
        file_path = Path(repo_path) / change["file"]
        if file_path.exists():
            content = file_path.read_text(errors="replace")
            changes_context.append(
                f"### {change['file']} ({change['action']})\n"
                f"Improvement: {change['improvement_id']}\n"
                f"Summary: {change['diff_summary']}\n"
                f"```\n{content[:3000]}\n```"
            )

    changes_text = "\n\n".join(changes_context)
    # Hard cap: keep changes under 40k chars total
    if len(changes_text) > 40_000:
        changes_text = changes_text[:40_000] + "\n\n... [TRUNCATED — too many changes to show all]"

    # Skip full file summary to stay under token limits — changes context is enough
    file_summary = ""

    result = chat_json(
        system=(
            "You are a principal engineer conducting a thorough code review. "
            "Review the changes made to this codebase and score them.\n\n"
            "Respond with JSON:\n"
            "{\n"
            '  "overall_score": float (1-10, where 7+ means production-ready),\n'
            '  "scores": {\n'
            '    "code_quality": float,\n'
            '    "features": float,\n'
            '    "security": float,\n'
            '    "compliance": float,\n'
            '    "integration": float,\n'
            '    "test_coverage_potential": float\n'
            "  },\n"
            '  "issues": [\n'
            '    {"severity": "critical|high|medium|low", "file": "path", "line": "approx", "description": "..."}\n'
            "  ],\n"
            '  "strengths": ["..."],\n'
            '  "summary": "2-3 sentence overall assessment"\n'
            "}\n\n"
            "Be rigorous but fair. Score each dimension 1-10."
        ),
        user=(
            f"Review these code changes:\n\n"
            f"## Changes Applied\n{changes_text}\n\n"
            f"## Full Codebase Context\n{file_summary}"
        ),
        max_tokens=4096,
    )

    # Determine pass/fail
    overall = result.get("overall_score", 0)
    from config import AUTO_MERGE_THRESHOLD
    result["passed"] = overall >= AUTO_MERGE_THRESHOLD

    log.info(
        "Review complete: score=%.1f, passed=%s, issues=%d",
        overall, result["passed"], len(result.get("issues", [])),
    )
    return result
