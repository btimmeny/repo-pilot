# Repo Pilot -- Architecture

## 1. System Overview

Repo Pilot is an autonomous code improvement pipeline that analyzes a target repository, suggests improvements across four categories (features, security, compliance, integration), executes the changes, reviews them, generates and runs tests, and merges everything back -- all orchestrated with Temporal.io and tracked with beads.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Clients                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐   │
│  │ curl / HTTP  │  │ Temporal UI  │  │ Future Clients               │   │
│  │ Clients      │  │              │  │ (Web Dashboard, CLI)         │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┬───────────────┘   │
│         │                 │                          │                   │
│         └─────────────────┼──────────────────────────┘                   │
│                           │                                             │
│                           ▼                                             │
│              ┌────────────────────────┐                                  │
│              │   FastAPI Application  │                                  │
│              │       (Port 8100)      │                                  │
│              └───────────┬────────────┘                                  │
│                          │                                              │
│              ┌───────────┴────────────┐                                  │
│              │   Temporal Server      │                                  │
│              │   (localhost:7233)     │                                  │
│              └───────────┬────────────┘                                  │
│                          │                                              │
│              ┌───────────┴────────────┐                                  │
│              │   Temporal Worker      │                                  │
│              │   (worker.py)          │                                  │
│              │   Polls task queue     │                                  │
│              └───────────┬────────────┘                                  │
│                          │                                              │
│         ┌────────────────┼────────────────┐                              │
│         │                │                │                              │
│         ▼                ▼                ▼                              │
│   ┌───────────┐   ┌───────────┐   ┌───────────┐                        │
│   │ OpenAI    │   │ Target    │   │ PostgreSQL│                        │
│   │ GPT-4.1   │   │ Repo (fs) │   │ (beads)   │                        │
│   └───────────┘   └───────────┘   └───────────┘                        │
└─────────────────────────────────────────────────────────────────────────┘
```

## 2. Project Structure

```
repo-pilot/
├── app.py                      # FastAPI application, REST endpoints, in-process fallback
├── config.py                   # Configuration from environment / .env
├── worker.py                   # Temporal worker — registers workflow + activities
├── models/
│   ├── __init__.py
│   └── schemas.py              # Dataclasses: Bead, Improvement, ReviewResult, TestCase, etc.
├── workflows/
│   ├── __init__.py
│   └── pipeline.py             # Temporal workflow: CodeImprovementPipeline (10 steps)
├── activities/
│   ├── __init__.py
│   ├── analyze.py              # Step 1: Scan repo → specification.md, graph.md, architecture.md
│   ├── suggest.py              # Step 2: AI suggests improvements in 4 categories
│   ├── execute_changes.py      # Step 4: AI generates and applies code modifications
│   ├── review.py               # Step 5: AI reviews changes, scores 1-10
│   ├── test_gen.py             # Step 6: AI generates test cases in 4 groups
│   ├── test_run.py             # Step 7: Run pytest per group, collect results
│   ├── git_ops.py              # Steps 4/8: Branch, commit, push, PR, auto-merge
│   ├── update_docs.py          # Step 9: Regenerate documentation post-merge
│   └── scaffold.py             # Standalone: Generate all missing best-practice files
├── beads/
│   ├── __init__.py
│   ├── tracker.py              # BeadTracker — in-memory chain with DB persistence
│   └── db.py                   # Postgres backing store for beads and pipeline runs
├── utils/
│   ├── __init__.py
│   ├── llm.py                  # OpenAI chat helpers (chat, chat_json) with retry
│   └── repo_scanner.py         # Filesystem scanner: tree, file contents, stats
├── requirements.txt            # Python dependencies
├── .env.example                # Required environment variables
└── .gitignore
```

## 3. Layer Architecture

The application follows a four-layer architecture:

### 3.1 API Layer (`app.py`)

- **Framework:** FastAPI with Uvicorn ASGI server
- **Responsibilities:**
  - Route definition and HTTP request handling
  - Temporal client connection management (via lifespan)
  - Pipeline triggering (Temporal workflow or in-process fallback)
  - Pipeline run listing and result retrieval
  - Bead query endpoints (by run, by status, by category)
  - Scaffold endpoint for best-practice file generation
- **Fallback:** When Temporal is unavailable, the pipeline runs in-process using `asyncio.get_running_loop().run_in_executor()` to keep activities non-blocking.

### 3.2 Workflow Layer (`workflows/pipeline.py`)

- **Framework:** Temporal.io Python SDK
- **Class:** `CodeImprovementPipeline` (decorated with `@workflow.defn`)
- **Responsibilities:**
  - Orchestrates 10 pipeline steps as a durable workflow
  - Each step is executed via `workflow.execute_activity()` with configurable timeouts
  - Tracks every step as a bead via `BeadTracker`
  - Handles errors gracefully -- pipeline status transitions to "failed" on exception
  - Produces a complete `run_record` dict with all phase outputs
- **Helper activities:** `_write_analysis_docs`, `_push_main`, `_save_run_log` are registered as Temporal activities alongside the main ones.

### 3.3 Activity Layer (`activities/`)

Each activity is a standalone function that performs a single pipeline step. Activities are CPU/IO-bound functions that the Temporal worker executes.

| Activity | File | Purpose |
|----------|------|---------|
| `analyze_repo` | `analyze.py` | Scan repo filesystem, call LLM to generate 3 docs |
| `suggest_improvements` | `suggest.py` | Call LLM per category to suggest 2-4 improvements each |
| `execute_changes` | `execute_changes.py` | Call LLM to generate code, write to filesystem |
| `review_changes` | `review.py` | Call LLM to score all changes 1-10 |
| `generate_tests` | `test_gen.py` | Call LLM to generate pytest files per group |
| `run_tests` | `test_run.py` | Write test files, run pytest subprocess per group |
| `create_branch` | `git_ops.py` | `git checkout -b` in target repo |
| `commit_changes` | `git_ops.py` | `git add -A && git commit` in target repo |
| `push_branch` | `git_ops.py` | `git push -u origin` in target repo |
| `create_merge_request` | `git_ops.py` | `gh pr create` via subprocess |
| `auto_merge` | `git_ops.py` | `gh pr merge` if score >= threshold |
| `checkout_main` | `git_ops.py` | `git checkout main && git pull` |
| `update_docs` | `update_docs.py` | Re-run `analyze_repo` and write updated docs |
| `scaffold_repo` | `scaffold.py` | Audit repo for missing files, generate via LLM |

All LLM-dependent activities use `utils/llm.py` which provides retry logic with exponential backoff on rate limit errors (up to 5 retries, starting at 10s delay).

### 3.4 Data Layer

#### Bead Tracking (`beads/tracker.py`, `beads/db.py`)

- **BeadTracker:** In-memory chain of `Bead` dataclass instances. Every state change (create, start, complete, fail, skip) is persisted to Postgres in real-time.
- **Postgres Tables:**
  - `pipeline_runs` -- One row per pipeline execution with JSONB columns for improvements, code_changes, review, test_results, merge_result, docs_updated, and repo_analysis.
  - `beads` -- One row per bead with FK to pipeline_runs, indexed on run_id, status, and category.
- **Graceful degradation:** If Postgres is unavailable, the tracker falls back to in-memory only. Pipeline runs are also saved as JSON files in `pipeline_runs/`.

#### Models (`models/schemas.py`)

All domain objects are Python dataclasses (not Pydantic BaseModel):

| Class | Purpose |
|-------|---------|
| `Bead` | Tracked unit of work (id, name, category, status, timing, metadata) |
| `Improvement` | Suggested code improvement (id, category, title, files_affected, changes) |
| `ReviewResult` | Code review scoring (overall_score, per-category scores, issues, summary) |
| `TestCase` | Single test case (id, group, name, test_code) |
| `TestResult` | Test suite result per group (total, passed, failed, errors, output) |
| `PipelineRun` | Complete pipeline execution record (all phase outputs) |

### 3.5 Utility Layer (`utils/`)

- **`llm.py`** -- OpenAI API wrapper
  - `chat(system, user, ...)` -- Returns raw string response
  - `chat_json(system, user, ...)` -- Returns parsed JSON dict
  - Singleton `OpenAI` client, configured via `config.OPENAI_API_KEY`
  - Rate limit retry: exponential backoff, 5 attempts, 10s base delay
- **`repo_scanner.py`** -- Filesystem scanner
  - `scan_repo(path)` -- Walks the repo, reads analyzable files, returns tree + file contents + stats
  - `build_tree_string(tree)` -- Visual tree for LLM context
  - `build_file_summary(files)` -- Prioritized file content digest within a character budget
  - Skips: `.git`, `.venv`, `node_modules`, `__pycache__`, etc.
  - Truncates files >8,000 chars, total context budget of 60,000 chars

## 4. Pipeline Execution

### 4.1 The 10-Step Pipeline

```
Step 1  ─ ANALYZE REPOSITORY
  └─ scan_repo() → LLM generates specification.md, graph.md, architecture.md

Step 2  ─ SUGGEST IMPROVEMENTS
  └─ LLM analyzes codebase in 4 categories (features, security, compliance, integration)
  └─ Produces 2-4 concrete improvements per category (8-16 total)

Step 3  ─ LOG TASKS
  └─ Each improvement becomes a tracked bead in the chain

Step 4  ─ EXECUTE CODE CHANGES
  └─ Create git branch
  └─ For each improvement/change: LLM generates code, writes to filesystem
  └─ Commit all changes

Step 5  ─ CODE REVIEW
  └─ LLM reviews all applied changes, scores 1-10 across 6 dimensions
  └─ Determines pass/fail against AUTO_MERGE_THRESHOLD (default 7.0)

Step 6  ─ GENERATE TESTS
  └─ LLM generates pytest files in 4 groups (features, security, compliance, integration)

Step 7  ─ EXECUTE TESTS
  └─ Run pytest subprocess per group, collect pass/fail/error counts
  └─ Commit test files

Step 8  ─ MERGE REQUEST
  └─ Push branch to origin
  └─ Create GitHub PR via gh CLI
  └─ Auto-merge if review score >= threshold

Step 9  ─ UPDATE DOCUMENTATION
  └─ Regenerate specification.md, graph.md, architecture.md
  └─ Commit and push updated docs

Step 10 ─ LOG & CONFIRM
  └─ Save detailed JSON log to pipeline_runs/
  └─ Persist final run record to Postgres
```

### 4.2 Execution Modes

| Mode | Trigger | How It Works |
|------|---------|-------------|
| **Temporal** (recommended) | `POST /pipeline/start` with Temporal connected | Workflow dispatched to Temporal, worker polls and executes activities with durable state |
| **In-process** (fallback) | `POST /pipeline/start` without Temporal | Pipeline runs directly in the FastAPI process using `run_in_executor` for each activity |

Both modes produce identical outputs: a run record with beads, improvements, changes, review, tests, and merge result.

### 4.3 Bead Lifecycle

Every discrete unit of work progresses through these states:

```
PENDING ──► RUNNING ──► COMPLETED
                   ├──► FAILED
                   └──► SKIPPED
```

- **PENDING** -- Bead created, not yet started
- **RUNNING** -- Activity execution in progress (start time recorded)
- **COMPLETED** -- Activity finished successfully (duration calculated)
- **FAILED** -- Activity threw an exception (error message recorded)
- **SKIPPED** -- Activity bypassed (e.g., improvement had no applicable changes)

## 5. External Dependencies

| Dependency | Purpose | Required |
|------------|---------|----------|
| **OpenAI API** (GPT-4.1) | LLM for analysis, suggestions, code gen, review, test gen | Yes |
| **Temporal Server** | Durable workflow orchestration | No (falls back to in-process) |
| **PostgreSQL** | Persistent bead and run storage | No (falls back to in-memory + JSON files) |
| **GitHub CLI** (`gh`) | PR creation and auto-merge | Yes (for merge step) |
| **Git** | Branch/commit/push operations | Yes |
| **pytest** | Test execution in target repos | Yes (for test step) |

## 6. Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | -- | Required. OpenAI API key |
| `TARGET_REPO_PATH` | -- | Default target repository path |
| `TEMPORAL_HOST` | `localhost:7233` | Temporal server address |
| `AUTO_MERGE_THRESHOLD` | `7.0` | Minimum review score for auto-merge (1-10) |
| `OPENAI_MODEL` | `gpt-4.1` | LLM model to use |
| `DATABASE_URL` | `postgresql://repopilot:repopilot@localhost:5432/repo_pilot` | Postgres connection string |

### File Analysis Configuration

| Constant | Value | Location |
|----------|-------|----------|
| `ANALYZABLE_EXTENSIONS` | `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.md`, `.yml`, `.yaml`, `.json`, `.toml`, `.cfg`, `.ini`, `.txt`, `.sh`, `.html`, `.css` | `config.py` |
| `MAX_FILE_SIZE` | 8,000 chars | `config.py` |
| `MAX_CONTEXT_CHARS` | 60,000 chars | `config.py` |
| `SKIP_DIRS` | `.git`, `.venv`, `node_modules`, `__pycache__`, etc. | `utils/repo_scanner.py` |

## 7. Security Considerations

1. **API key in environment:** `OPENAI_API_KEY` is loaded from `.env` (never committed) and used server-side only.
2. **No authentication on API:** The FastAPI application has no auth middleware. Access control should be handled at the network level or added before production deployment.
3. **Subprocess execution:** Git and pytest commands are run via `subprocess.run` with `cwd` set to the target repo and timeouts enforced (30s for git, 120s for tests).
4. **LLM-generated code execution:** Generated test code is written to disk and executed via pytest. This is inherently risky and should only be run against trusted repos in sandboxed environments.
5. **No secrets in logs:** Pipeline run logs (JSON files) contain code changes and review results but not API keys.

## 8. Scalability Path

| Concern | Current State | Scale Path |
|---------|--------------|------------|
| **Workflow durability** | Temporal or in-process fallback | Temporal cluster with multiple workers |
| **Concurrent pipelines** | Single worker, one pipeline at a time | Multiple workers on separate task queues |
| **LLM throughput** | Sequential API calls, retry on rate limit | Parallel activity execution, model routing |
| **Storage** | Postgres + JSON files | Postgres with partitioning, S3 for run logs |
| **Target repos** | Local filesystem access required | Remote clone via git URL, ephemeral containers |
| **Observability** | Python logging, bead chain | OpenTelemetry, Temporal metrics, structured JSON logging |

## 9. Error Handling Strategy

1. **Pipeline level:** The workflow wraps all steps in a try/except. On failure, status transitions to "failed", error message is recorded, and the run log is still saved.
2. **Activity level:** Individual activities catch exceptions and return structured error dicts (e.g., `{"status": "failed", "error": "..."}`).
3. **LLM level:** Rate limit errors trigger exponential backoff retry (5 attempts). JSON parse failures return an error dict with the raw response.
4. **Git level:** Git command failures are logged as warnings; the `_git` helper returns stdout+stderr so callers can inspect.
5. **Database level:** Postgres connection failures cause graceful degradation to in-memory tracking with console warnings.
6. **Test execution level:** Subprocess timeouts (120s) prevent runaway tests. Individual group failures don't block other groups.

## 10. Key Design Decisions

1. **Temporal-optional:** The pipeline works with or without Temporal, making local development simple while providing durable orchestration in production.
2. **Bead-based audit trail:** Every pipeline step is tracked as a bead with timing, status, and metadata -- providing complete observability of what happened and how long each step took.
3. **Dual persistence:** Run records are saved to both Postgres (structured queries) and JSON files (human-readable, portable), with graceful fallback if either is unavailable.
4. **LLM as the engine:** All analysis, suggestion, code generation, review, and test generation are delegated to GPT-4.1. The pipeline code is pure orchestration.
5. **Subprocess for git/tests:** Git operations and test execution use `subprocess.run` rather than Python libraries, keeping the interface simple and avoiding library version conflicts with target repos.
6. **Character budgets:** The repo scanner enforces file-level (8K chars) and total (60K chars) limits to stay within LLM context windows, with priority sorting to maximize useful content.
7. **Threshold-gated merge:** Auto-merge only proceeds if the AI review score meets a configurable threshold (default 7.0/10), providing a quality gate.
8. **Four-category improvement taxonomy:** Improvements are categorized as features, security, compliance, or integration -- providing balanced coverage and structured test generation.
