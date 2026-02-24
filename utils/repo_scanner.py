"""
Repo scanner — reads a target repository and builds a structured representation.
"""

from __future__ import annotations

import logging
from pathlib import Path

import config

log = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache",
    ".pytest_cache", "site", ".tox", "dist", "build", "egg-info",
}


def scan_repo(repo_path: Path | str) -> dict:
    """
    Scan a repository and return its structure + file contents.

    Returns:
        {
            "tree": ["relative/path/to/file", ...],
            "files": {
                "relative/path": {"content": "...", "size": int, "ext": ".py"}
            },
            "stats": {"total_files": int, "total_lines": int, "languages": {...}}
        }
    """
    repo_path = Path(repo_path)
    if not repo_path.is_dir():
        raise ValueError(f"Repository path does not exist: {repo_path}")

    tree: list[str] = []
    files: dict[str, dict] = {}
    lang_counts: dict[str, int] = {}
    total_lines = 0

    for path in sorted(repo_path.rglob("*")):
        # Skip hidden/ignored directories
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue

        rel = str(path.relative_to(repo_path))
        ext = path.suffix.lower()

        tree.append(rel)

        if ext in config.ANALYZABLE_EXTENSIONS:
            try:
                content = path.read_text(errors="replace")
                if len(content) > config.MAX_FILE_SIZE:
                    content = content[:config.MAX_FILE_SIZE] + "\n... [TRUNCATED]"
                lines = content.count("\n") + 1
                total_lines += lines
                files[rel] = {
                    "content": content,
                    "size": path.stat().st_size,
                    "lines": lines,
                    "ext": ext,
                }
                lang_counts[ext] = lang_counts.get(ext, 0) + lines
            except Exception as e:
                log.warning("Could not read %s: %s", rel, e)

    log.info(
        "Scanned %s: %d files, %d analyzable, %d total lines",
        repo_path.name, len(tree), len(files), total_lines,
    )

    return {
        "tree": tree,
        "files": files,
        "stats": {
            "total_files": len(tree),
            "analyzable_files": len(files),
            "total_lines": total_lines,
            "languages": lang_counts,
        },
    }


def build_tree_string(tree: list[str]) -> str:
    """Build a visual tree string from a flat file list."""
    lines = []
    for path_str in tree:
        parts = path_str.split("/")
        indent = "  " * (len(parts) - 1)
        lines.append(f"{indent}├── {parts[-1]}")
    return "\n".join(lines)


def build_file_summary(files: dict[str, dict], max_chars: int | None = None) -> str:
    """Build a concise summary of file contents, staying within a character budget.
    
    Prioritizes .py files over docs/config, and sorts by size (smallest first)
    to maximize the number of files included.
    """
    max_chars = max_chars or config.MAX_CONTEXT_CHARS

    # Prioritize: .py first, then .yml/.yaml, then everything else
    priority = {".py": 0, ".yml": 1, ".yaml": 1, ".sh": 2}
    sorted_files = sorted(
        files.items(),
        key=lambda kv: (priority.get(kv[1]["ext"], 3), kv[1].get("lines", 0)),
    )

    parts = []
    total = 0
    for rel_path, info in sorted_files:
        entry = f"### {rel_path} ({info['lines']} lines)\n```{info['ext'].lstrip('.')}\n{info['content']}\n```\n"
        if total + len(entry) > max_chars:
            parts.append(f"\n... [{len(sorted_files) - len(parts)} more files omitted due to context budget]\n")
            break
        parts.append(entry)
        total += len(entry)
    return "\n".join(parts)
