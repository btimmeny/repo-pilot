"""
Activity: Test Generation — creates test cases in four groups
(features, security, compliance, integration) for the modified codebase.
"""

from __future__ import annotations

import logging
from pathlib import Path

from utils.llm import chat_json
from utils.repo_scanner import scan_repo, build_file_summary

log = logging.getLogger(__name__)

TEST_GROUPS = ["features", "security", "compliance", "integration"]

GROUP_PROMPTS = {
    "features": (
        "Generate pytest test cases that verify feature correctness: "
        "API endpoints return expected responses, agents produce valid output, "
        "data layer functions return correct data, edge cases are handled, "
        "and the pipeline produces complete results."
    ),
    "security": (
        "Generate pytest test cases for security: "
        "input validation rejects malicious input, API key is not exposed in responses, "
        "rate limiting headers are present, CORS is properly configured, "
        "sensitive data is not leaked in error messages, and authentication is enforced."
    ),
    "compliance": (
        "Generate pytest test cases for regulatory compliance: "
        "PHI/PII is not exposed in API responses, audit logging captures access events, "
        "drug interaction warnings are always surfaced, prescription data requires auth, "
        "guardrails prevent medical advice, and data retention rules are followed."
    ),
    "integration": (
        "Generate pytest test cases for ecosystem integration: "
        "health endpoint returns proper status, OpenAPI schema is valid, "
        "structured logging produces parseable output, error responses follow RFC 7807, "
        "API versioning headers are present, and webhook callbacks fire correctly."
    ),
}


def generate_tests(repo_path: str, improvements: list[dict], applied_changes: list[dict]) -> list[dict]:
    """
    Generate test cases for all four groups.

    Returns:
        List of test file dicts:
        [{"group": "...", "file": "tests/test_X.py", "test_count": int, "content": "..."}]
    """
    log.info("Generating tests for %s", repo_path)
    scan = scan_repo(repo_path)
    file_summary = build_file_summary(scan["files"], max_chars=30_000)

    # Build changes context
    changes_ctx = "\n".join(
        f"- [{c['improvement_id']}] {c['file']}: {c['diff_summary']}"
        for c in applied_changes if c["status"] == "applied"
    )

    test_files = []

    for group in TEST_GROUPS:
        log.info("Generating %s tests", group)
        result = chat_json(
            system=(
                "You are a senior QA engineer. Generate a complete pytest test file.\n\n"
                "Respond with JSON:\n"
                '{"test_file_content": "...complete Python test file...", '
                '"test_count": int, '
                '"test_names": ["test_name_1", "test_name_2"]}\n\n'
                "REQUIREMENTS:\n"
                "- Use pytest conventions (functions starting with test_)\n"
                "- Import from the target repo's modules correctly\n"
                "- Use fixtures where appropriate\n"
                "- Include docstrings for each test\n"
                "- Tests should be runnable standalone\n"
                "- Mock external API calls (OpenAI) — never call real APIs in tests\n"
                "- Use httpx.AsyncClient with FastAPI's TestClient pattern for API tests\n\n"
                f"FOCUS: {GROUP_PROMPTS[group]}"
            ),
            user=(
                f"Generate {group} tests for this codebase:\n\n"
                f"## Applied Changes\n{changes_ctx}\n\n"
                f"## Codebase (key files)\n{file_summary}"
            ),
            max_tokens=8192,
        )

        content = result.get("test_file_content", "")
        test_count = result.get("test_count", 0)
        test_names = result.get("test_names", [])
        file_name = f"tests/test_{group}.py"

        test_files.append({
            "group": group,
            "file": file_name,
            "test_count": test_count,
            "test_names": test_names,
            "content": content,
        })

    log.info("Generated %d test files with %d total tests",
             len(test_files), sum(t["test_count"] for t in test_files))
    return test_files
