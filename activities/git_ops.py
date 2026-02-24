"""
Activity: Git Operations — handles branching, committing, merging, and pushing.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import config

log = logging.getLogger(__name__)


def create_branch(repo_path: str, branch_name: str) -> dict:
    """Create and checkout a new branch."""
    log.info("Creating branch: %s", branch_name)
    _git(repo_path, "checkout", "-b", branch_name)
    return {"branch": branch_name, "status": "created"}


def commit_changes(repo_path: str, message: str) -> dict:
    """Stage all changes and commit."""
    log.info("Committing: %s", message)
    _git(repo_path, "add", "-A")

    # Check if there's anything to commit
    result = _git(repo_path, "status", "--porcelain")
    if not result.strip():
        log.info("Nothing to commit")
        return {"status": "nothing_to_commit", "message": message}

    _git(repo_path, "commit", "-m", message)
    sha = _git(repo_path, "rev-parse", "HEAD").strip()
    return {"status": "committed", "message": message, "sha": sha}


def push_branch(repo_path: str, branch_name: str) -> dict:
    """Push branch to origin."""
    log.info("Pushing branch: %s", branch_name)
    _git(repo_path, "push", "-u", "origin", branch_name)
    return {"status": "pushed", "branch": branch_name}


def create_merge_request(repo_path: str, branch_name: str, title: str, body: str) -> dict:
    """Create a GitHub pull request using gh CLI."""
    log.info("Creating PR: %s", title)
    try:
        output = subprocess.run(
            [
                "gh", "pr", "create",
                "--title", title,
                "--body", body,
                "--base", "main",
                "--head", branch_name,
            ],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=30,
        )
        if output.returncode == 0:
            pr_url = output.stdout.strip()
            log.info("PR created: %s", pr_url)
            return {"status": "created", "url": pr_url, "branch": branch_name}
        else:
            log.error("PR creation failed: %s", output.stderr)
            return {"status": "failed", "error": output.stderr}
    except Exception as e:
        log.error("PR creation error: %s", e)
        return {"status": "failed", "error": str(e)}


def auto_merge(repo_path: str, review_score: float, threshold: float | None = None) -> dict:
    """Merge the PR if the review score meets the threshold."""
    threshold = threshold or config.AUTO_MERGE_THRESHOLD
    log.info("Auto-merge check: score=%.1f, threshold=%.1f", review_score, threshold)

    if review_score < threshold:
        log.info("Score below threshold — merge BLOCKED")
        return {
            "status": "blocked",
            "reason": f"Review score {review_score:.1f} < threshold {threshold:.1f}",
            "score": review_score,
            "threshold": threshold,
        }

    # Merge via gh CLI
    try:
        output = subprocess.run(
            ["gh", "pr", "merge", "--merge", "--delete-branch"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=30,
        )
        if output.returncode == 0:
            log.info("PR merged successfully")
            return {"status": "merged", "score": review_score, "threshold": threshold}
        else:
            log.error("Merge failed: %s", output.stderr)
            return {"status": "failed", "error": output.stderr}
    except Exception as e:
        log.error("Merge error: %s", e)
        return {"status": "failed", "error": str(e)}


def checkout_main(repo_path: str) -> dict:
    """Switch back to main and pull latest."""
    _git(repo_path, "checkout", "main")
    _git(repo_path, "pull", "origin", "main")
    return {"status": "on_main"}


def _git(repo_path: str, *args: str) -> str:
    """Run a git command in the target repo."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=repo_path,
        timeout=30,
    )
    if result.returncode != 0 and "nothing to commit" not in result.stdout:
        log.warning("git %s failed: %s", " ".join(args), result.stderr)
    return result.stdout + result.stderr
