# Repo Pilot

An autonomous code improvement pipeline that analyzes a repository, suggests improvements across four categories, executes the changes, reviews them, generates and runs tests, and merges everything back — all orchestrated with Temporal.io and tracked with beads.

## Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                         REPO PILOT PIPELINE                         │
│                                                                     │
│  Step 1 ─ ANALYZE REPOSITORY                                       │
│    └─ Scan all files → generate specification.md, graph.md,        │
│       architecture.md                                               │
│                                                                     │
│  Step 2 ─ SUGGEST IMPROVEMENTS                                     │
│    └─ AI analyzes codebase in 4 categories:                        │
│       • Features    (better functionality, UX, error handling)     │
│       • Security    (input validation, auth, secrets, CORS)        │
│       • Compliance  (HIPAA, PCI-DSS, FDA 21 CFR Part 11)          │
│       • Integration (observability, Docker, CI/CD, messaging)      │
│                                                                     │
│  Step 3 ─ LOG TASKS (Beads + Temporal)                             │
│    └─ Each improvement becomes a tracked bead in the chain         │
│                                                                     │
│  Step 4 ─ EXECUTE CODE CHANGES                                     │
│    └─ AI generates and applies code modifications                  │
│    └─ Commit to feature branch                                     │
│                                                                     │
│  Step 5 ─ CODE REVIEW                                              │
│    └─ AI reviews all changes, scores 1-10                          │
│    └─ Scores: code quality, features, security, compliance,        │
│       integration, test coverage potential                          │
│                                                                     │
│  Step 6 ─ GENERATE TESTS (4 groups)                                │
│    └─ Features tests, Security tests, Compliance tests,            │
│       Integration tests                                             │
│                                                                     │
│  Step 7 ─ EXECUTE TESTS                                            │
│    └─ Run pytest per group, collect pass/fail results              │
│                                                                     │
│  Step 8 ─ MERGE REQUEST                                            │
│    └─ Push branch, create GitHub PR                                │
│    └─ Auto-merge if review score ≥ threshold (default 7.0)         │
│                                                                     │
│  Step 9 ─ UPDATE DOCUMENTATION                                     │
│    └─ Regenerate specification.md, graph.md, architecture.md       │
│    └─ Commit and push to GitHub                                    │
│                                                                     │
│  Step 10 ─ LOG & CONFIRM                                           │
│    └─ Save detailed JSON log with all beads, changes, results      │
│    └─ Confirm done                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

## Beads

Every discrete unit of work is tracked as a **bead** — a logged task with:
- ID, name, category
- Status (pending → running → completed/failed/skipped)
- Timing (start, end, duration)
- Input/output summaries
- Metadata (improvement ID, priority, files affected)

The bead chain provides a complete audit trail of the pipeline execution.

## Setup

```bash
cd repo-pilot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set your OpenAI API key and target repo
cp .env.example .env
# Edit .env: set OPENAI_API_KEY and TARGET_REPO_PATH
```

## Run

### Option A: With Temporal (recommended for production)

```bash
# Terminal 1: Start Temporal dev server
temporal server start-dev

# Terminal 2: Start the Temporal worker
python worker.py

# Terminal 3: Start the API
uvicorn app:app --port 8100

# Terminal 4: Trigger the pipeline
curl -X POST http://localhost:8100/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/retail-agent-swarm"}'
```

### Option B: Without Temporal (in-process fallback)

```bash
# Just start the API (it will run the pipeline in-process)
uvicorn app:app --port 8100

# Trigger
curl -X POST http://localhost:8100/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/retail-agent-swarm"}'
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (includes Temporal connection status) |
| `POST` | `/pipeline/start` | Start a code improvement pipeline |
| `GET` | `/pipeline/{run_id}` | Get pipeline run status and results |
| `GET` | `/pipeline/runs` | List all pipeline runs |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required. OpenAI API key |
| `TARGET_REPO_PATH` | — | Default target repository path |
| `TEMPORAL_HOST` | `localhost:7233` | Temporal server address |
| `AUTO_MERGE_THRESHOLD` | `7.0` | Minimum review score for auto-merge (1-10) |
| `OPENAI_MODEL` | `gpt-4.1` | LLM model to use |

## Pipeline Output

Each run produces a detailed JSON log in `pipeline_runs/` containing:
- **Bead chain** — full audit trail of every task
- **Improvements suggested** — with category, priority, affected files
- **Code changes applied** — per-file diffs and status
- **Code review** — scores, issues, strengths
- **Test results** — pass/fail per group with output
- **Merge result** — PR URL, auto-merge decision
- **Updated docs** — regenerated specification, graph, architecture
