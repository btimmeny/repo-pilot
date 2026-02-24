"""
Activity: Suggest Improvements — analyzes the codebase and proposes changes
in four categories: features, security, compliance, integration.
"""

from __future__ import annotations

import json
import logging

from utils.llm import chat_json
from utils.repo_scanner import scan_repo, build_file_summary

log = logging.getLogger(__name__)

CATEGORIES = ["features", "security", "compliance", "integration"]

CATEGORY_PROMPTS = {
    "features": (
        "Suggest improvements to make this codebase more feature-rich and useful. "
        "Consider: better error handling, new API endpoints, improved data models, "
        "caching, pagination, filtering, webhook support, retry logic, better logging, "
        "configuration flexibility, and user experience improvements."
    ),
    "security": (
        "Suggest security improvements for this codebase. Consider: "
        "input validation and sanitization, rate limiting, authentication/authorization, "
        "API key rotation, secrets management, CORS hardening, request size limits, "
        "dependency vulnerability scanning, SQL injection prevention, XSS prevention, "
        "secure headers, and audit logging."
    ),
    "compliance": (
        "Suggest regulatory compliance improvements for this codebase. "
        "Given this is a retail pharmacy system, consider: "
        "HIPAA data handling (PHI protection, access controls, audit trails), "
        "PCI-DSS for any payment data, FDA 21 CFR Part 11 for electronic records, "
        "state pharmacy board regulations, data retention policies, "
        "consent management, and accessibility (ADA/WCAG)."
    ),
    "integration": (
        "Suggest ecosystem integration improvements for this codebase. Consider: "
        "OpenTelemetry/observability, structured logging (JSON), health check depth, "
        "Docker containerization, CI/CD pipeline config, message queue integration "
        "(Kafka/Redis Streams), database migration support, API versioning, "
        "OpenAPI schema improvements, webhook callbacks, and event-driven patterns."
    ),
}


def suggest_improvements(repo_path: str) -> list[dict]:
    """
    Analyze the repo and suggest improvements in all four categories.

    Returns:
        List of improvement dicts, each with:
        {
            "id": "IMP-001",
            "category": "features|security|compliance|integration",
            "title": "...",
            "description": "...",
            "priority": "high|medium|low",
            "files_affected": ["path/to/file.py"],
            "changes": [{"file": "...", "description": "...", "code_hint": "..."}]
        }
    """
    log.info("Scanning repo for improvement suggestions: %s", repo_path)
    scan = scan_repo(repo_path)
    file_summary = build_file_summary(scan["files"])

    all_improvements = []
    imp_counter = 1

    for category in CATEGORIES:
        log.info("Generating %s improvements", category)
        result = chat_json(
            system=(
                "You are a senior software engineer performing a code review. "
                "You MUST respond with valid JSON in this exact format:\n"
                '{"improvements": [\n'
                '  {"title": "...", "description": "...", "priority": "high|medium|low",\n'
                '   "files_affected": ["path/to/file.py"],\n'
                '   "changes": [{"file": "path/to/file.py", "description": "what to change", '
                '"code_hint": "brief code snippet or approach"}]}\n'
                "]}\n\n"
                "Suggest 2-4 concrete, actionable improvements. Each change must reference "
                "specific files and describe exactly what to modify.\n\n"
                f"FOCUS: {CATEGORY_PROMPTS[category]}"
            ),
            user=f"Analyze this codebase and suggest {category} improvements:\n\n{file_summary}",
            max_tokens=4096,
        )

        for imp in result.get("improvements", []):
            imp["id"] = f"IMP-{imp_counter:03d}"
            imp["category"] = category
            imp_counter += 1
            all_improvements.append(imp)

    log.info("Generated %d total improvements across %d categories", len(all_improvements), len(CATEGORIES))
    return all_improvements
