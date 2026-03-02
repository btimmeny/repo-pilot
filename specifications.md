# Repo Pilot -- Specifications

## 1. Overview

**Repo Pilot** is an autonomous code improvement pipeline that analyzes a target repository, suggests improvements, executes code changes, reviews them, generates and runs tests, and merges back to main. The system is orchestrated by Temporal.io and tracked with a bead-based audit trail persisted to PostgreSQL.

### 1.1 Problem Statement

Development teams accumulate technical debt, security gaps, compliance risks, and integration shortcomings over time. Manual identification and remediation is slow and inconsistent. Repo Pilot automates the cycle of *analyze → improve → review → test → merge* to continuously elevate code quality.

### 1.2 Target Users

| User | Use Case |
|------|----------|
| Individual developers | Run pipeline against personal projects to catch issues |
| Development teams | Integrate as a CI-adjacent tool for automated improvement PRs |
| Platform / DevOps engineers | Deploy as a service to scan multiple repositories |
| Compliance officers | Use compliance category to audit regulatory adherence |

### 1.3 Core Concepts

| Concept | Definition |
|---------|------------|
| **Pipeline** | A single end-to-end execution of the 10-step improvement cycle against one repository |
| **Bead** | A tracked unit of work with status, timing, and metadata — the atomic audit element |
| **Improvement** | A suggested code change belonging to one of four categories |
| **Category** | One of FEATURES, SECURITY, COMPLIANCE, or INTEGRATION |
| **Run Record** | The complete output of a pipeline execution, including all phase results |
| **Scaffold** | A standalone operation that generates missing best-practice files for a repo |

## 2. Functional Requirements

### Pipeline Execution

| ID | Requirement | Status |
|----|-------------|--------|
| FR-001 | System shall scan a target repository and produce a structural analysis including file tree, file contents, and statistics | Implemented |
| FR-002 | System shall generate three documentation artifacts from analysis: specification.md, graph.md, architecture.md | Implemented |
| FR-003 | System shall suggest 2-4 improvements per category (features, security, compliance, integration) using LLM analysis | Implemented |
| FR-004 | System shall create a git branch in the target repo and execute code changes for each accepted improvement | Implemented |
| FR-005 | System shall review all applied changes and produce a scored assessment (1-10 scale) across six dimensions | Implemented |
| FR-006 | System shall generate pytest test files in four groups corresponding to the four improvement categories | Implemented |
| FR-007 | System shall execute generated tests via pytest subprocess and collect pass/fail/error results per group | Implemented |
| FR-008 | System shall push the branch, create a GitHub PR, and auto-merge if the review score meets the configured threshold | Implemented |
| FR-009 | System shall regenerate documentation after merge to reflect the updated codebase | Implemented |
| FR-010 | System shall save a complete run log as JSON and persist the run record to PostgreSQL | Implemented |

### Bead Tracking

| ID | Requirement | Status |
|----|-------------|--------|
| FR-011 | Each pipeline step shall be tracked as a bead with unique ID, name, category, status, and timing | Implemented |
| FR-012 | Bead state transitions (create, start, complete, fail, skip) shall be persisted to PostgreSQL in real-time | Implemented |
| FR-013 | System shall support querying beads by run ID, status, and category | Implemented |
| FR-014 | System shall provide a summary endpoint returning bead counts by status | Implemented |
| FR-015 | Bead tracking shall degrade gracefully to in-memory-only when Postgres is unavailable | Implemented |

### REST API

| ID | Requirement | Status |
|----|-------------|--------|
| FR-016 | System shall expose POST /pipeline/start to trigger a new pipeline run | Implemented |
| FR-017 | System shall expose GET /pipeline/{run_id} to retrieve run status and results | Implemented |
| FR-018 | System shall expose GET /pipeline/runs to list pipeline runs with optional status filter and limit | Implemented |
| FR-019 | System shall expose GET /health for liveness checks | Implemented |
| FR-020 | System shall expose GET /beads/{run_id} with optional status and category query filters | Implemented |
| FR-021 | System shall expose GET /beads/{run_id}/summary for bead status counts | Implemented |
| FR-022 | System shall expose GET /bead/{bead_id} for individual bead lookup | Implemented |
| FR-023 | System shall expose POST /scaffold to generate missing best-practice files for a repo | Implemented |

### Execution Modes

| ID | Requirement | Status |
|----|-------------|--------|
| FR-024 | System shall execute pipeline via Temporal workflow when Temporal server is available | Implemented |
| FR-025 | System shall fall back to in-process execution when Temporal is unavailable | Implemented |
| FR-026 | Both execution modes shall produce identical output structures | Implemented |

### Scaffold

| ID | Requirement | Status |
|----|-------------|--------|
| FR-027 | System shall detect the language/framework stack of a target repository | Implemented |
| FR-028 | System shall audit for missing best-practice files (README, CI, tests, config, docs) | Implemented |
| FR-029 | System shall generate missing files using LLM with stack-aware prompts | Implemented |
| FR-030 | System shall commit and push generated scaffold files to the target repo | Implemented |

## 3. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-001 | Pipeline execution shall complete within 30 minutes for repositories under 100 files | Best effort (LLM-dependent) |
| NFR-002 | LLM calls shall retry on rate-limit errors with exponential backoff | 5 retries, 10s base delay |
| NFR-003 | Test execution subprocess shall timeout after 120 seconds per group | Enforced |
| NFR-004 | Git operations shall timeout after 30 seconds per command | Enforced |
| NFR-005 | System shall not commit or log API keys or credentials | Enforced |
| NFR-006 | System shall continue operating with degraded functionality when Postgres is unavailable | Implemented |
| NFR-007 | System shall continue operating with in-process fallback when Temporal is unavailable | Implemented |
| NFR-008 | File analysis shall respect character budgets (8K per file, 60K total) to stay within LLM context limits | Enforced |

## 4. Data Models

### 4.1 BeadStatus (Enum)

```
PENDING   — Created, not yet started
RUNNING   — Execution in progress
COMPLETED — Finished successfully
FAILED    — Threw an exception
SKIPPED   — Bypassed (no applicable work)
```

### 4.2 ImprovementCategory (Enum)

```
FEATURES    — Error handling, endpoints, data models, caching, pagination
SECURITY    — Input validation, rate limiting, auth, secrets, CORS
COMPLIANCE  — HIPAA, PCI-DSS, FDA 21 CFR Part 11, data retention, consent
INTEGRATION — OpenTelemetry, structured logging, health checks, Docker, CI/CD
```

### 4.3 Bead

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | UUID, unique identifier |
| `name` | str | Human-readable step name |
| `category` | str | Improvement category or "pipeline" for system beads |
| `status` | BeadStatus | Current lifecycle state |
| `started_at` | datetime | When execution began |
| `completed_at` | datetime | When execution ended |
| `duration_sec` | float | Elapsed time in seconds |
| `input_summary` | str | Brief description of inputs |
| `output_summary` | str | Brief description of outputs |
| `error` | str | Error message if failed |
| `metadata` | dict | Arbitrary key-value data |

### 4.4 Improvement

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | UUID identifier |
| `category` | ImprovementCategory | One of the four categories |
| `title` | str | Short title |
| `description` | str | Detailed explanation |
| `priority` | str | "high", "medium", or "low" |
| `files_affected` | list[str] | Files to be modified or created |
| `changes` | list[dict] | Per-file change descriptors with code_hint |

### 4.5 ReviewResult

| Field | Type | Description |
|-------|------|-------------|
| `overall_score` | float | 1-10 aggregate score |
| `category_scores` | dict | Per-dimension scores (correctness, style, security, testing, performance, documentation) |
| `issues` | list[dict] | Identified problems with severity and location |
| `summary` | str | Narrative review summary |

### 4.6 TestCase

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | UUID identifier |
| `group` | str | Test group name (features, security, compliance, integration) |
| `name` | str | Test function name |
| `test_code` | str | Complete pytest code |

### 4.7 TestResult

| Field | Type | Description |
|-------|------|-------------|
| `group` | str | Test group name |
| `total` | int | Total test count |
| `passed` | int | Passing tests |
| `failed` | int | Failing tests |
| `errors` | int | Tests with errors |
| `output` | str | Pytest stdout/stderr |

### 4.8 PipelineRun

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | str | UUID identifier |
| `target_repo` | str | Path to target repository |
| `branch_name` | str | Git branch created for changes |
| `status` | str | pending, running, completed, failed |
| `improvements` | list[Improvement] | Suggested improvements |
| `code_changes` | list[dict] | Applied changes |
| `review` | ReviewResult | Code review result |
| `test_results` | list[TestResult] | Test execution results |
| `merge_result` | dict | PR creation and merge outcome |
| `docs_updated` | list[str] | Documentation files regenerated |
| `repo_analysis` | dict | Repository analysis output |

## 5. API Surface

### 5.1 Pipeline Endpoints

#### `POST /pipeline/start`

Start a new pipeline run.

**Request Body:**
```json
{
  "repo_path": "/absolute/path/to/target/repo"
}
```

**Response (202 Accepted):**
```json
{
  "run_id": "uuid-string",
  "status": "started",
  "message": "Pipeline started via temporal | in-process"
}
```

#### `GET /pipeline/{run_id}`

Get pipeline run status and results.

**Response (200 OK):**
```json
{
  "run_id": "uuid-string",
  "status": "completed",
  "target_repo": "/path/to/repo",
  "branch_name": "repo-pilot/uuid",
  "improvements": [...],
  "code_changes": [...],
  "review": {...},
  "test_results": [...],
  "merge_result": {...},
  "docs_updated": [...],
  "repo_analysis": {...}
}
```

**Lookup order:** Postgres → JSON file → Temporal workflow query.

#### `GET /pipeline/runs`

List pipeline runs.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | str | (none) | Filter by status |
| `limit` | int | 50 | Maximum results |

**Response:** Array of run records.

### 5.2 Bead Endpoints

#### `GET /beads/{run_id}`

Get all beads for a pipeline run.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | str | (none) | Filter by bead status |
| `category` | str | (none) | Filter by category |

**Response:** Array of bead objects.

#### `GET /beads/{run_id}/summary`

Get bead status counts for a run.

**Response:**
```json
{
  "total": 12,
  "pending": 0,
  "running": 0,
  "completed": 10,
  "failed": 1,
  "skipped": 1
}
```

#### `GET /bead/{bead_id}`

Get a single bead by ID.

**Response:** Single bead object.

### 5.3 Utility Endpoints

#### `GET /health`

**Response:**
```json
{
  "status": "healthy",
  "temporal": "connected" | "disconnected"
}
```

#### `POST /scaffold`

Generate missing best-practice files.

**Request Body:**
```json
{
  "repo_path": "/absolute/path/to/target/repo"
}
```

**Response:** Object with generated file paths and content.

## 6. Improvement Category Prompts

Each category has a dedicated system prompt that guides the LLM to produce targeted improvements:

### FEATURES
> Suggest improvements related to: error handling and edge cases, new utility functions or endpoints, data model enhancements, caching strategies, pagination, retry mechanisms, logging improvements, configuration flexibility, user experience.

### SECURITY
> Suggest improvements related to: input validation and sanitization, rate limiting, authentication/authorization gaps, secrets management, CORS configuration, secure headers, SQL injection prevention, XSS prevention, dependency vulnerabilities, secure session handling.

### COMPLIANCE
> Suggest improvements related to: HIPAA compliance (PHI handling, access controls, audit logging), PCI-DSS (payment data handling, encryption), FDA 21 CFR Part 11 (electronic records, audit trails), state-level privacy regulations, data retention and deletion policies, consent management, accessibility (ADA/WCAG).

### INTEGRATION
> Suggest improvements related to: OpenTelemetry/distributed tracing, structured logging (JSON format), health check endpoints, Docker/container readiness, CI/CD pipeline integration, API versioning, webhook support, event-driven architecture, external service clients, message queue integration.

## 7. Review Scoring Dimensions

The code review activity scores changes on a 1-10 scale across six dimensions:

| Dimension | What It Measures |
|-----------|-----------------|
| **Correctness** | Does the code work as intended? Are there bugs? |
| **Style** | Does it follow project conventions and clean code principles? |
| **Security** | Are there vulnerabilities or insecure patterns introduced? |
| **Testing** | Is the code testable? Are edge cases considered? |
| **Performance** | Are there efficiency concerns or potential bottlenecks? |
| **Documentation** | Are changes documented? Are docstrings present? |

The `overall_score` is derived from these dimensions. If `overall_score >= AUTO_MERGE_THRESHOLD` (default 7.0), the PR is auto-merged.

## 8. Configuration

### Required

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4.1 access |

### Optional (with defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `TARGET_REPO_PATH` | (none) | Default target repository path |
| `TEMPORAL_HOST` | `localhost:7233` | Temporal server address |
| `AUTO_MERGE_THRESHOLD` | `7.0` | Minimum review score for auto-merge (1-10) |
| `OPENAI_MODEL` | `gpt-4.1` | LLM model identifier |
| `DATABASE_URL` | `postgresql://repopilot:repopilot@localhost:5432/repo_pilot` | PostgreSQL connection string |
| `IMPROVEMENT_BRANCH_PREFIX` | `repo-pilot/` | Git branch name prefix |

### Internal Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `ANALYZABLE_EXTENSIONS` | 16 extensions | File types included in repo scanning |
| `MAX_FILE_SIZE` | 8,000 chars | Per-file truncation limit |
| `MAX_CONTEXT_CHARS` | 60,000 chars | Total LLM context budget |
| `SKIP_DIRS` | 10 patterns | Directories excluded from scanning |
| `MAX_RETRIES` | 5 | LLM rate-limit retry attempts |
| `BASE_DELAY` | 10 seconds | Initial retry backoff delay |

## 9. Quality Gates

### Auto-Merge Decision

```
IF review.overall_score >= AUTO_MERGE_THRESHOLD:
    → gh pr merge --merge --delete-branch
    → checkout main, pull latest
    → update documentation
ELSE:
    → PR remains open for manual review
    → merge_result.merged = false
```

### Test Execution

- Tests are run per group (features, security, compliance, integration)
- Each group runs in a separate pytest subprocess with 120s timeout
- Individual group failures do not block other groups
- All results are recorded in the run record regardless of pass/fail

### Review Threshold

The default `AUTO_MERGE_THRESHOLD` of 7.0 means improvements must score at least 7 out of 10 to be auto-merged. This can be tuned per deployment:
- **Conservative (8-9):** Only high-quality changes merge automatically
- **Moderate (6-7):** Most reasonable changes merge
- **Aggressive (4-5):** Most changes merge, manual review for serious issues only

## 10. Error Handling

| Layer | Strategy |
|-------|----------|
| **Pipeline** | Wrap all steps in try/except. On failure: set status to "failed", record error, still save run log |
| **Activity** | Return structured error dict `{"status": "failed", "error": "..."}` rather than raising |
| **LLM** | Exponential backoff retry on rate limits (5 attempts). JSON parse failures return error dict with raw response |
| **Git** | Log warnings on command failures. Return stdout+stderr for caller inspection |
| **Database** | Graceful degradation to in-memory tracking when Postgres is unreachable |
| **Tests** | Subprocess timeout (120s) prevents runaway tests. Per-group isolation prevents cascade failures |

## 11. Future Considerations

| Area | Potential Enhancement |
|------|----------------------|
| **Authentication** | Add API key or OAuth middleware to FastAPI |
| **Multi-repo** | Support running pipeline against multiple repos in a single invocation |
| **Custom categories** | Allow users to define custom improvement categories with their own prompts |
| **Webhooks** | Trigger pipelines from GitHub webhook events (push, PR) |
| **Dashboard** | Web UI for viewing pipeline runs, beads, and trends over time |
| **Model routing** | Use different LLM models for different activities based on cost/quality tradeoffs |
| **Caching** | Cache repo scans and LLM responses to reduce redundant work |
| **Parallel activities** | Execute independent activities concurrently within Temporal |
| **Incremental analysis** | Only analyze changed files since last pipeline run |
| **Custom thresholds** | Per-category merge thresholds instead of a single global score |
