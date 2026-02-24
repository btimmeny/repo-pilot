"""
Activity: Test Runner — writes test files to the target repo and executes them with pytest.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def run_tests(repo_path: str, test_files: list[dict]) -> list[dict]:
    """
    Write generated test files into the target repo and run them with pytest.

    Returns:
        List of test results per group:
        [{"group": "...", "total": int, "passed": int, "failed": int, "errors": [...], "output": "..."}]
    """
    repo = Path(repo_path)
    tests_dir = repo / "tests"
    tests_dir.mkdir(exist_ok=True)

    # Write conftest if missing
    conftest = tests_dir / "conftest.py"
    if not conftest.exists():
        conftest.write_text(
            '"""Shared pytest fixtures."""\n\n'
            "import sys\n"
            "from pathlib import Path\n\n"
            "# Ensure the repo root is importable\n"
            "sys.path.insert(0, str(Path(__file__).parent.parent))\n"
        )

    # Write __init__.py if missing
    init = tests_dir / "__init__.py"
    if not init.exists():
        init.write_text("")

    # Write test files
    for tf in test_files:
        file_path = repo / tf["file"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(tf["content"])
        log.info("Wrote test file: %s (%d tests)", tf["file"], tf["test_count"])

    # Run pytest per group
    results = []
    for tf in test_files:
        group = tf["group"]
        test_path = repo / tf["file"]
        log.info("Running %s tests: %s", group, test_path)

        try:
            proc = subprocess.run(
                [
                    "python", "-m", "pytest",
                    str(test_path),
                    "-v",
                    "--tb=short",
                    "--no-header",
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(repo),
                env=_build_env(repo),
            )
            output = proc.stdout + proc.stderr
            passed, failed, errors = _parse_pytest_output(output)

            results.append({
                "group": group,
                "file": tf["file"],
                "total": passed + failed,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "output": output[:5000],
                "exit_code": proc.returncode,
            })
            log.info(
                "%s tests: %d passed, %d failed (exit=%d)",
                group, passed, failed, proc.returncode,
            )

        except subprocess.TimeoutExpired:
            results.append({
                "group": group,
                "file": tf["file"],
                "total": 0,
                "passed": 0,
                "failed": 0,
                "errors": ["Test execution timed out after 120s"],
                "output": "TIMEOUT",
                "exit_code": -1,
            })
            log.error("%s tests: TIMEOUT", group)

        except Exception as e:
            results.append({
                "group": group,
                "file": tf["file"],
                "total": 0,
                "passed": 0,
                "failed": 0,
                "errors": [str(e)],
                "output": str(e),
                "exit_code": -1,
            })
            log.error("%s tests: ERROR: %s", group, e)

    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    log.info("All tests complete: %d passed, %d failed", total_passed, total_failed)
    return results


def _build_env(repo: Path) -> dict:
    """Build environment for subprocess, including the repo's venv if present."""
    import os
    env = os.environ.copy()
    venv = repo / ".venv"
    if venv.exists():
        env["VIRTUAL_ENV"] = str(venv)
        env["PATH"] = f"{venv / 'bin'}:{env.get('PATH', '')}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _parse_pytest_output(output: str) -> tuple[int, int, list[str]]:
    """Parse pytest output to extract pass/fail counts."""
    passed = 0
    failed = 0
    errors = []

    for line in output.splitlines():
        line_lower = line.lower().strip()
        if " passed" in line_lower and ("failed" in line_lower or "passed" in line_lower):
            # Summary line like "5 passed, 2 failed"
            import re
            p = re.search(r"(\d+)\s+passed", line_lower)
            f = re.search(r"(\d+)\s+failed", line_lower)
            if p:
                passed = int(p.group(1))
            if f:
                failed = int(f.group(1))
        elif line_lower.startswith("failed") or "error" in line_lower:
            if line.strip():
                errors.append(line.strip())

    return passed, failed, errors
