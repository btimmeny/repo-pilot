"""
Activity: Scaffold Repository — analyzes an existing repo and generates
all missing best-practice files to make it "review-ready".

Detects:
  - Language/framework stack
  - Existing files (won't overwrite)
  - Missing documentation, CI, tests, config

Generates:
  - README.md (if missing/thin)
  - docs/specification.md, architecture.md, graph.md
  - CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, CHANGELOG.md
  - .env.example
  - CI workflow (.github/workflows/ci.yml)
  - PR template (.github/PULL_REQUEST_TEMPLATE.md)
  - Issue templates (.github/ISSUE_TEMPLATE/bug_report.md, feature_request.md)
  - Linter/formatter config (pyproject.toml sections or .eslintrc)
  - Makefile with common commands
  - tests/ scaffold if empty
  - ADR template (docs/adr/001-template.md)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from utils.llm import chat, chat_json
from utils.repo_scanner import scan_repo, build_tree_string, build_file_summary

log = logging.getLogger(__name__)

# ── Checklist of best-practice files ──────────────────────────────────

CHECKLIST = [
    # (relative path, category, description)
    ("README.md", "docs", "Project overview, setup, usage"),
    ("CONTRIBUTING.md", "docs", "Contribution guidelines"),
    ("SECURITY.md", "docs", "Vulnerability reporting process"),
    ("CODE_OF_CONDUCT.md", "docs", "Community standards"),
    ("CHANGELOG.md", "docs", "Version history"),
    ("LICENSE", "legal", "License file"),
    (".env.example", "config", "Required environment variables"),
    ("Makefile", "tooling", "Common commands"),
    ("docs/specification.md", "docs", "Functional specification"),
    ("docs/architecture.md", "docs", "System architecture"),
    ("docs/graph.md", "docs", "Dependency/flow graphs"),
    ("docs/adr/001-template.md", "docs", "Architecture decision record template"),
    (".github/workflows/ci.yml", "ci", "CI pipeline"),
    (".github/PULL_REQUEST_TEMPLATE.md", "ci", "PR template"),
    (".github/ISSUE_TEMPLATE/bug_report.md", "ci", "Bug report template"),
    (".github/ISSUE_TEMPLATE/feature_request.md", "ci", "Feature request template"),
]


def _detect_stack(tree: list[str], files: dict) -> dict:
    """Detect the language, framework, and package manager from repo contents."""
    extensions = {}
    for rel, info in files.items():
        ext = info.get("ext", "")
        extensions[ext] = extensions.get(ext, 0) + info.get("lines", 0)

    has = lambda name: any(name in f for f in tree)

    stack = {
        "languages": [],
        "frameworks": [],
        "package_manager": None,
        "test_framework": None,
        "has_tests": False,
        "has_ci": False,
        "has_docker": False,
    }

    # Languages
    if ".py" in extensions:
        stack["languages"].append("python")
    if ".ts" in extensions or ".tsx" in extensions:
        stack["languages"].append("typescript")
    if ".js" in extensions or ".jsx" in extensions:
        stack["languages"].append("javascript")
    if ".go" in extensions:
        stack["languages"].append("go")
    if ".rs" in extensions:
        stack["languages"].append("rust")

    # Frameworks
    if has("fastapi") or has("FastAPI"):
        stack["frameworks"].append("fastapi")
    if has("flask"):
        stack["frameworks"].append("flask")
    if has("django"):
        stack["frameworks"].append("django")
    if has("next.config") or has("nextjs"):
        stack["frameworks"].append("nextjs")
    if has("package.json"):
        stack["frameworks"].append("node")

    # Package managers
    if has("pyproject.toml"):
        stack["package_manager"] = "pyproject.toml"
    elif has("requirements.txt"):
        stack["package_manager"] = "requirements.txt"
    elif has("package.json"):
        stack["package_manager"] = "package.json"
    elif has("Cargo.toml"):
        stack["package_manager"] = "Cargo.toml"
    elif has("go.mod"):
        stack["package_manager"] = "go.mod"

    # Tests
    stack["has_tests"] = any("test" in f.lower() for f in tree)
    if has("pytest") or has("conftest.py"):
        stack["test_framework"] = "pytest"
    elif has("jest.config"):
        stack["test_framework"] = "jest"
    elif has("vitest"):
        stack["test_framework"] = "vitest"

    # CI
    stack["has_ci"] = has(".github/workflows") or has(".gitlab-ci") or has("Jenkinsfile")

    # Docker
    stack["has_docker"] = has("Dockerfile") or has("docker-compose")

    return stack


def _audit_repo(repo_path: Path, tree: list[str]) -> dict:
    """Check which best-practice files exist and which are missing."""
    existing = []
    missing = []

    for rel_path, category, description in CHECKLIST:
        full = repo_path / rel_path
        if full.exists():
            # Check if README is thin (< 20 lines)
            if rel_path == "README.md":
                try:
                    content = full.read_text()
                    if content.count("\n") < 20:
                        missing.append({
                            "path": rel_path, "category": category,
                            "description": description, "note": "exists but thin (<20 lines)",
                        })
                        continue
                except Exception:
                    pass
            existing.append({"path": rel_path, "category": category, "description": description})
        else:
            missing.append({"path": rel_path, "category": category, "description": description})

    # Check for tests directory structure
    tests_dir = repo_path / "tests"
    if not tests_dir.is_dir():
        missing.append({
            "path": "tests/", "category": "testing",
            "description": "Test directory with unit/integration structure",
        })

    return {"existing": existing, "missing": missing}


def scaffold_repo(repo_path: str) -> dict:
    """
    Analyze a repo and generate all missing best-practice files.

    Returns:
        {
            "stack": {...},
            "audit": {"existing": [...], "missing": [...]},
            "created": ["path1", "path2", ...],
            "skipped": ["path1", ...],
        }
    """
    repo = Path(repo_path)
    log.info("Scaffolding repository: %s", repo)

    # Step 1: Scan
    scan = scan_repo(repo_path)
    tree = scan["tree"]
    files = scan["files"]
    tree_str = build_tree_string(tree)
    file_summary = build_file_summary(files, max_chars=30_000)

    # Step 2: Detect stack
    stack = _detect_stack(tree, files)
    log.info("Detected stack: %s", stack)

    # Step 3: Audit
    audit = _audit_repo(repo, tree)
    log.info("Audit: %d existing, %d missing", len(audit["existing"]), len(audit["missing"]))

    if not audit["missing"]:
        log.info("Repository already has all best-practice files!")
        return {"stack": stack, "audit": audit, "created": [], "skipped": []}

    # Step 4: Generate missing files via LLM
    context = (
        f"## Repository: {repo.name}\n\n"
        f"## Detected Stack\n```json\n{json.dumps(stack, indent=2)}\n```\n\n"
        f"## File Tree\n```\n{tree_str}\n```\n\n"
        f"## File Contents (sample)\n{file_summary}"
    )

    missing_paths = [m["path"] for m in audit["missing"]]
    created = []
    skipped = []

    # Group related files for efficient LLM calls
    _generate_docs(repo, context, stack, missing_paths, created, skipped)
    _generate_ci(repo, context, stack, missing_paths, created, skipped)
    _generate_tooling(repo, context, stack, missing_paths, created, skipped)
    _generate_templates(repo, context, stack, missing_paths, created, skipped)
    _generate_tests_scaffold(repo, context, stack, missing_paths, created, skipped)

    log.info("Scaffolding complete: %d created, %d skipped", len(created), len(skipped))
    return {"stack": stack, "audit": audit, "created": created, "skipped": skipped}


# ── Generators ────────────────────────────────────────────────────────

def _write_file(repo: Path, rel_path: str, content: str, created: list, skipped: list) -> None:
    """Write a file, creating parent dirs. Skip if it already exists."""
    full = repo / rel_path
    if full.exists():
        skipped.append(rel_path)
        return
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    created.append(rel_path)
    log.info("Created: %s", rel_path)


def _generate_docs(repo: Path, context: str, stack: dict, missing: list, created: list, skipped: list):
    """Generate documentation files."""
    doc_files = [m for m in missing if m in (
        "README.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
        "CHANGELOG.md", "docs/specification.md", "docs/architecture.md", "docs/graph.md",
    )]
    if not doc_files:
        return

    primary_lang = stack["languages"][0] if stack["languages"] else "python"

    # README
    if "README.md" in missing:
        readme = chat(
            system=(
                "You are a senior technical writer. Generate a comprehensive README.md for this project. "
                "Include: project title, badges (CI, license), description, features, "
                "prerequisites, installation, quick start, configuration (.env vars), "
                "project structure, API docs (if applicable), testing, deployment, "
                "contributing link, license. Use clean markdown with emojis sparingly."
            ),
            user=f"Generate a best-in-class README.md:\n\n{context}",
            max_tokens=4096,
        )
        _write_file(repo, "README.md", readme, created, skipped)

    # CONTRIBUTING
    if "CONTRIBUTING.md" in missing:
        contrib = chat(
            system=(
                "Generate a CONTRIBUTING.md file. Include: how to set up the dev environment, "
                "branch naming conventions, commit message format (conventional commits), "
                "PR process, code style guidelines, testing requirements, "
                f"and issue/bug reporting. Target language: {primary_lang}."
            ),
            user=f"Generate CONTRIBUTING.md for:\n\n{context}",
            max_tokens=3000,
        )
        _write_file(repo, "CONTRIBUTING.md", contrib, created, skipped)

    # SECURITY
    if "SECURITY.md" in missing:
        security = f"""# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT** open a public issue.
2. Email: [security contact email]
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a timeline for a fix.

## Security Best Practices

- Never commit secrets, API keys, or credentials
- Use `.env` files for sensitive configuration (see `.env.example`)
- Keep dependencies up to date
- Run security scanning as part of CI
"""
        _write_file(repo, "SECURITY.md", security, created, skipped)

    # CODE_OF_CONDUCT
    if "CODE_OF_CONDUCT.md" in missing:
        coc = """# Contributor Covenant Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our
community a harassment-free experience for everyone, regardless of age, body
size, visible or invisible disability, ethnicity, sex characteristics, gender
identity and expression, level of experience, education, socio-economic status,
nationality, personal appearance, race, religion, or sexual identity and orientation.

## Our Standards

Examples of behavior that contributes to a positive environment:

- Using welcoming and inclusive language
- Being respectful of differing viewpoints and experiences
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

Examples of unacceptable behavior:

- The use of sexualized language or imagery
- Trolling, insulting or derogatory comments, and personal or political attacks
- Public or private harassment
- Publishing others' private information without explicit permission
- Other conduct which could reasonably be considered inappropriate

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the project team. All complaints will be reviewed and investigated.

## Attribution

This Code of Conduct is adapted from the [Contributor Covenant](https://www.contributor-covenant.org), version 2.1.
"""
        _write_file(repo, "CODE_OF_CONDUCT.md", coc, created, skipped)

    # CHANGELOG
    if "CHANGELOG.md" in missing:
        changelog = """# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project setup

### Changed

### Fixed

### Removed
"""
        _write_file(repo, "CHANGELOG.md", changelog, created, skipped)

    # specification.md, architecture.md, graph.md — use the analyze activity's approach
    if "docs/specification.md" in missing:
        spec = chat(
            system=(
                "You are a senior technical writer. Generate a comprehensive specification.md. "
                "Include: project overview, functional requirements (table with IDs), "
                "data models, API contracts, behaviors, guardrails, acceptance criteria."
            ),
            user=f"Generate specification.md:\n\n{context}",
            max_tokens=6000,
        )
        _write_file(repo, "docs/specification.md", spec, created, skipped)

    if "docs/architecture.md" in missing:
        arch = chat(
            system=(
                "You are a principal engineer. Generate architecture.md. "
                "Include: system overview, layer diagram, component descriptions, "
                "data layer, external deps, security, scalability, error handling."
            ),
            user=f"Generate architecture.md:\n\n{context}",
            max_tokens=6000,
        )
        _write_file(repo, "docs/architecture.md", arch, created, skipped)

    if "docs/graph.md" in missing:
        graph = chat(
            system=(
                "You are a software architect. Generate graph.md with Mermaid diagrams. "
                "Include: component dependency graph, data flow, sequence diagrams. "
                "Use ```mermaid code blocks."
            ),
            user=f"Generate graph.md:\n\n{context}",
            max_tokens=6000,
        )
        _write_file(repo, "docs/graph.md", graph, created, skipped)

    # ADR template
    if "docs/adr/001-template.md" in missing:
        adr = """# ADR-001: [Title]

## Status
Proposed | Accepted | Deprecated | Superseded

## Context
What is the issue that we're seeing that is motivating this decision or change?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or more difficult to do because of this change?

### Positive
-

### Negative
-

### Neutral
-
"""
        _write_file(repo, "docs/adr/001-template.md", adr, created, skipped)


def _generate_ci(repo: Path, context: str, stack: dict, missing: list, created: list, skipped: list):
    """Generate CI/CD configuration."""
    if ".github/workflows/ci.yml" not in missing:
        return

    primary_lang = stack["languages"][0] if stack["languages"] else "python"

    ci = chat(
        system=(
            f"Generate a GitHub Actions CI workflow (.github/workflows/ci.yml) for a {primary_lang} project. "
            "Include:\n"
            "- Trigger on push to main and pull_request\n"
            "- Matrix testing if appropriate\n"
            "- Steps: checkout, setup language, install deps, lint, type-check, test, coverage\n"
            f"- Package manager: {stack['package_manager'] or 'auto-detect'}\n"
            f"- Test framework: {stack['test_framework'] or 'auto-detect'}\n"
            "Output ONLY the YAML file content, no markdown fences."
        ),
        user=f"Generate ci.yml for:\n\n{context}",
        max_tokens=2000,
    )
    # Strip markdown fences if LLM wraps it
    ci = ci.strip()
    if ci.startswith("```"):
        ci = "\n".join(ci.split("\n")[1:])
    if ci.endswith("```"):
        ci = "\n".join(ci.split("\n")[:-1])

    _write_file(repo, ".github/workflows/ci.yml", ci.strip() + "\n", created, skipped)


def _generate_tooling(repo: Path, context: str, stack: dict, missing: list, created: list, skipped: list):
    """Generate Makefile and .env.example."""
    primary_lang = stack["languages"][0] if stack["languages"] else "python"

    if "Makefile" in missing:
        makefile = chat(
            system=(
                f"Generate a Makefile for a {primary_lang} project. Include targets:\n"
                "- help (default, lists targets)\n"
                "- install (install dependencies)\n"
                "- dev (start dev server)\n"
                "- test (run tests)\n"
                "- lint (run linter)\n"
                "- format (run formatter)\n"
                "- typecheck (run type checker)\n"
                "- clean (remove build artifacts)\n"
                "- docker-up / docker-down (if applicable)\n"
                f"Package manager: {stack['package_manager'] or 'auto-detect'}. "
                f"Test framework: {stack['test_framework'] or 'auto-detect'}. "
                "Output ONLY the Makefile content, no markdown fences. Use tabs for indentation."
            ),
            user=f"Generate Makefile for:\n\n{context}",
            max_tokens=2000,
        )
        makefile = makefile.strip()
        if makefile.startswith("```"):
            makefile = "\n".join(makefile.split("\n")[1:])
        if makefile.endswith("```"):
            makefile = "\n".join(makefile.split("\n")[:-1])
        _write_file(repo, "Makefile", makefile.strip() + "\n", created, skipped)

    if ".env.example" in missing:
        env_example = chat(
            system=(
                "Generate a .env.example file for this project. "
                "List all environment variables the project needs based on the code, "
                "with placeholder values and comments explaining each. "
                "Output ONLY the file content, no markdown fences."
            ),
            user=f"Generate .env.example:\n\n{context}",
            max_tokens=1000,
        )
        env_example = env_example.strip()
        if env_example.startswith("```"):
            env_example = "\n".join(env_example.split("\n")[1:])
        if env_example.endswith("```"):
            env_example = "\n".join(env_example.split("\n")[:-1])
        _write_file(repo, ".env.example", env_example.strip() + "\n", created, skipped)


def _generate_templates(repo: Path, context: str, stack: dict, missing: list, created: list, skipped: list):
    """Generate PR and issue templates."""
    if ".github/PULL_REQUEST_TEMPLATE.md" in missing:
        pr_template = """## Description
<!-- What does this PR do? -->

## Type of Change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)

## How Has This Been Tested?
<!-- Describe the tests you ran -->

## Checklist
- [ ] My code follows the project's style guidelines
- [ ] I have performed a self-review of my code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or my feature works
- [ ] New and existing unit tests pass locally with my changes
"""
        _write_file(repo, ".github/PULL_REQUEST_TEMPLATE.md", pr_template, created, skipped)

    if ".github/ISSUE_TEMPLATE/bug_report.md" in missing:
        bug = """---
name: Bug Report
about: Create a report to help us improve
title: "[BUG] "
labels: bug
---

## Describe the Bug
A clear and concise description of what the bug is.

## To Reproduce
Steps to reproduce the behavior:
1. ...
2. ...
3. ...

## Expected Behavior
A clear description of what you expected to happen.

## Actual Behavior
What actually happened.

## Environment
- OS: [e.g., macOS 14.0]
- Python/Node version: [e.g., 3.12]
- Package versions: [relevant packages]

## Screenshots / Logs
If applicable, add screenshots or log output.

## Additional Context
Any other context about the problem.
"""
        _write_file(repo, ".github/ISSUE_TEMPLATE/bug_report.md", bug, created, skipped)

    if ".github/ISSUE_TEMPLATE/feature_request.md" in missing:
        feature = """---
name: Feature Request
about: Suggest an idea for this project
title: "[FEATURE] "
labels: enhancement
---

## Is your feature request related to a problem?
A clear description of what the problem is. Ex. I'm always frustrated when...

## Describe the Solution You'd Like
A clear description of what you want to happen.

## Describe Alternatives You've Considered
A description of any alternative solutions or features you've considered.

## Additional Context
Add any other context or screenshots about the feature request.
"""
        _write_file(repo, ".github/ISSUE_TEMPLATE/feature_request.md", feature, created, skipped)


def _generate_tests_scaffold(repo: Path, context: str, stack: dict, missing: list, created: list, skipped: list):
    """Generate test directory structure if missing."""
    if "tests/" not in missing:
        return

    primary_lang = stack["languages"][0] if stack["languages"] else "python"
    tests_dir = repo / "tests"

    if primary_lang == "python":
        _write_file(repo, "tests/__init__.py", "", created, skipped)

        conftest = chat(
            system=(
                "Generate a pytest conftest.py with useful shared fixtures for this project. "
                "Include fixtures for: temporary directories, mock environment variables, "
                "sample data, and any project-specific fixtures based on the code. "
                "Output ONLY Python code, no markdown fences."
            ),
            user=f"Generate tests/conftest.py:\n\n{context}",
            max_tokens=2000,
        )
        conftest = conftest.strip()
        if conftest.startswith("```"):
            conftest = "\n".join(conftest.split("\n")[1:])
        if conftest.endswith("```"):
            conftest = "\n".join(conftest.split("\n")[:-1])
        _write_file(repo, "tests/conftest.py", conftest.strip() + "\n", created, skipped)

        # Create subdirectories
        for subdir in ["unit", "integration"]:
            _write_file(repo, f"tests/{subdir}/__init__.py", "", created, skipped)

        # Generate a sample unit test
        sample_test = chat(
            system=(
                "Generate a sample pytest unit test file for this project. "
                "Test the most important/core functionality. Use mocks where needed. "
                "Include at least 3 test functions. Output ONLY Python code, no markdown fences."
            ),
            user=f"Generate tests/unit/test_core.py:\n\n{context}",
            max_tokens=2000,
        )
        sample_test = sample_test.strip()
        if sample_test.startswith("```"):
            sample_test = "\n".join(sample_test.split("\n")[1:])
        if sample_test.endswith("```"):
            sample_test = "\n".join(sample_test.split("\n")[:-1])
        _write_file(repo, "tests/unit/test_core.py", sample_test.strip() + "\n", created, skipped)

    elif primary_lang in ("javascript", "typescript"):
        _write_file(repo, "tests/.gitkeep", "", created, skipped)

    log.info("Test scaffold created")
