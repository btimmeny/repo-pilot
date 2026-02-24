"""
Activity: Execute Changes — takes approved improvements and generates
the actual code modifications, then applies them to the codebase.
"""

from __future__ import annotations

import logging
from pathlib import Path

from utils.llm import chat_json, chat
from utils.repo_scanner import scan_repo

log = logging.getLogger(__name__)


def execute_changes(repo_path: str, improvements: list[dict]) -> list[dict]:
    """
    For each improvement, generate concrete code changes and apply them.

    Returns:
        List of applied changes:
        [{"improvement_id": "...", "file": "...", "status": "applied|failed", "diff_summary": "..."}]
    """
    log.info("Executing %d improvements on %s", len(improvements), repo_path)
    repo = Path(repo_path)
    applied = []

    for imp in improvements:
        imp_id = imp["id"]
        log.info("Executing %s: %s", imp_id, imp["title"])

        for change in imp.get("changes", []):
            target_file = change.get("file", "")
            file_path = repo / target_file

            if not file_path.exists():
                # New file — generate it
                result = _generate_new_file(imp, change, repo_path)
                if result:
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(result["content"])
                    applied.append({
                        "improvement_id": imp_id,
                        "file": target_file,
                        "action": "created",
                        "status": "applied",
                        "diff_summary": f"New file: {len(result['content'])} chars",
                    })
                    log.info("Created new file: %s", target_file)
                else:
                    applied.append({
                        "improvement_id": imp_id,
                        "file": target_file,
                        "action": "create",
                        "status": "failed",
                        "diff_summary": "Failed to generate file content",
                    })
            else:
                # Existing file — generate modifications
                original = file_path.read_text()
                result = _modify_file(imp, change, target_file, original)
                if result and result.get("new_content"):
                    new_content = result["new_content"]
                    if new_content != original:
                        file_path.write_text(new_content)
                        applied.append({
                            "improvement_id": imp_id,
                            "file": target_file,
                            "action": "modified",
                            "status": "applied",
                            "diff_summary": result.get("summary", "Modified"),
                        })
                        log.info("Modified: %s", target_file)
                    else:
                        applied.append({
                            "improvement_id": imp_id,
                            "file": target_file,
                            "action": "modify",
                            "status": "skipped",
                            "diff_summary": "No changes needed",
                        })
                else:
                    applied.append({
                        "improvement_id": imp_id,
                        "file": target_file,
                        "action": "modify",
                        "status": "failed",
                        "diff_summary": "Failed to generate modifications",
                    })

    applied_count = sum(1 for a in applied if a["status"] == "applied")
    log.info("Applied %d/%d changes successfully", applied_count, len(applied))
    return applied


def _generate_new_file(improvement: dict, change: dict, repo_path: str) -> dict | None:
    """Generate content for a new file."""
    try:
        content = chat(
            system=(
                "You are a senior Python developer. Generate the complete file content "
                "for a new file to be added to the codebase. Return ONLY the file content, "
                "no markdown fences or explanation. The code must be production-quality, "
                "well-documented, and follow the existing codebase conventions."
            ),
            user=(
                f"Create a new file for this improvement:\n\n"
                f"**Improvement:** {improvement['title']}\n"
                f"**Description:** {improvement['description']}\n"
                f"**File:** {change['file']}\n"
                f"**What it should do:** {change['description']}\n"
                f"**Code hint:** {change.get('code_hint', 'N/A')}\n"
                f"**Repository:** {repo_path}"
            ),
            max_tokens=4096,
        )
        return {"content": content}
    except Exception as e:
        log.error("Failed to generate new file %s: %s", change["file"], e)
        return None


def _modify_file(improvement: dict, change: dict, file_path: str, original: str) -> dict | None:
    """Generate modifications for an existing file."""
    try:
        result = chat_json(
            system=(
                "You are a senior Python developer. Given an existing file and a requested "
                "improvement, produce the modified file content.\n\n"
                'Respond with JSON: {"new_content": "...full file content...", '
                '"summary": "brief description of changes"}\n\n'
                "IMPORTANT:\n"
                "- Return the COMPLETE file content (not a diff)\n"
                "- Preserve all existing functionality\n"
                "- Follow the existing code style\n"
                "- Add imports at the top if needed\n"
                "- Do not remove or weaken existing features"
            ),
            user=(
                f"Modify this file for the improvement:\n\n"
                f"**Improvement:** {improvement['title']}\n"
                f"**Description:** {improvement['description']}\n"
                f"**What to change:** {change['description']}\n"
                f"**Code hint:** {change.get('code_hint', 'N/A')}\n\n"
                f"**Current file ({file_path}):**\n```\n{original}\n```"
            ),
            max_tokens=8192,
        )
        return result
    except Exception as e:
        log.error("Failed to modify %s: %s", file_path, e)
        return None
