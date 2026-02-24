"""
Activity: Analyze Repository — scans the target repo and generates
specification.md, graph.md, and architecture.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

from utils.llm import chat, chat_json
from utils.repo_scanner import scan_repo, build_tree_string, build_file_summary

log = logging.getLogger(__name__)


def analyze_repo(repo_path: str) -> dict:
    """
    Scan the repo and produce three documentation artifacts.

    Returns:
        {
            "specification": "...",
            "graph": "...",
            "architecture": "...",
            "stats": {...}
        }
    """
    log.info("Analyzing repository: %s", repo_path)
    scan = scan_repo(repo_path)
    tree_str = build_tree_string(scan["tree"])
    file_summary = build_file_summary(scan["files"])

    context = (
        f"## Repository Structure\n```\n{tree_str}\n```\n\n"
        f"## Repository Stats\n{scan['stats']}\n\n"
        f"## File Contents\n{file_summary}"
    )

    # ── Generate specification.md ──
    log.info("Generating specification.md")
    specification = chat(
        system=(
            "You are a senior technical writer. Given a repository's structure and code, "
            "produce a comprehensive SPECIFICATION.md document. Include:\n"
            "- Project overview and purpose\n"
            "- Functional requirements (table with IDs)\n"
            "- Data models and schemas\n"
            "- API contracts (endpoints, request/response)\n"
            "- Agent behaviors and responsibilities\n"
            "- Guardrails and safety rules\n"
            "- Acceptance criteria\n"
            "Use proper markdown formatting with tables, headers, and code blocks."
        ),
        user=f"Analyze this repository and generate a complete specification document:\n\n{context}",
        max_tokens=8192,
    )

    # ── Generate graph.md ──
    log.info("Generating graph.md")
    graph = chat(
        system=(
            "You are a software architect. Given a repository's code, produce a GRAPH.md document "
            "that shows the system's relationships using Mermaid diagrams. Include:\n"
            "- Component dependency graph (which modules import which)\n"
            "- Data flow diagram (how data moves through the system)\n"
            "- Agent interaction sequence diagram\n"
            "- Parallel execution flow diagram\n"
            "- API request flow diagram\n"
            "Use ```mermaid code blocks for all diagrams. Add explanatory text between diagrams."
        ),
        user=f"Analyze this repository and generate comprehensive Mermaid diagrams:\n\n{context}",
        max_tokens=8192,
    )

    # ── Generate architecture.md ──
    log.info("Generating architecture.md")
    architecture = chat(
        system=(
            "You are a principal engineer. Given a repository's code, produce an ARCHITECTURE.md "
            "document. Include:\n"
            "- System overview and layer diagram (ASCII art)\n"
            "- Component descriptions and responsibilities\n"
            "- Parallel execution strategy and thread pool design\n"
            "- Data layer design\n"
            "- External dependencies and integration points\n"
            "- Security considerations\n"
            "- Scalability path\n"
            "- Error handling strategy\n"
            "Use proper markdown with tables, code blocks, and ASCII diagrams."
        ),
        user=f"Analyze this repository and generate a complete architecture document:\n\n{context}",
        max_tokens=8192,
    )

    return {
        "specification": specification,
        "graph": graph,
        "architecture": architecture,
        "stats": scan["stats"],
    }
