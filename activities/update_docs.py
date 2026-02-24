"""
Activity: Update Documentation — regenerates specification.md, graph.md,
and architecture.md after code changes have been applied and merged.
"""

from __future__ import annotations

import logging
from pathlib import Path

from activities.analyze import analyze_repo

log = logging.getLogger(__name__)


def update_docs(repo_path: str) -> list[str]:
    """
    Regenerate the three documentation files in the target repo's docs/ directory.

    Returns:
        List of updated file paths.
    """
    log.info("Updating documentation for %s", repo_path)
    repo = Path(repo_path)
    docs_dir = repo / "docs"
    docs_dir.mkdir(exist_ok=True)

    analysis = analyze_repo(repo_path)

    updated = []
    for name, key in [
        ("specification.md", "specification"),
        ("graph.md", "graph"),
        ("architecture.md", "architecture"),
    ]:
        file_path = docs_dir / name
        content = analysis.get(key, "")
        if content:
            file_path.write_text(content)
            updated.append(str(file_path.relative_to(repo)))
            log.info("Updated: %s (%d chars)", name, len(content))
        else:
            log.warning("No content generated for %s", name)

    return updated
