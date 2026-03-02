# Repo Pilot -- System Graphs

## 1. Pipeline Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        PIPELINE EXECUTION FLOW                           │
│                                                                          │
│   POST /pipeline/start                                                   │
│          │                                                               │
│          ▼                                                               │
│   ┌──────────────┐     ┌──────────────┐                                  │
│   │ Temporal     │ OR  │ In-Process   │                                  │
│   │ Connected?   │────►│ Fallback     │                                  │
│   └──────┬───────┘     └──────┬───────┘                                  │
│          │                    │                                          │
│          ▼                    ▼                                          │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 1: Analyze Repository          │                               │
│   │  scan_repo() → LLM × 3 calls        │                               │
│   │  Output: specification.md, graph.md, │                               │
│   │          architecture.md             │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 2: Suggest Improvements        │                               │
│   │  LLM × 4 calls (one per category)   │                               │
│   │  Output: 8-16 improvements           │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 3: Log Tasks as Beads          │                               │
│   │  Each improvement → tracked bead     │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 4: Execute Code Changes        │                               │
│   │  git checkout -b → LLM per change   │                               │
│   │  → write files → git commit          │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 5: Code Review                 │                               │
│   │  LLM scores 1-10 across 6 dims      │                               │
│   │  Output: pass/fail decision          │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 6: Generate Tests              │                               │
│   │  LLM × 4 calls (one per group)      │                               │
│   │  Output: 4 pytest files              │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 7: Execute Tests               │                               │
│   │  pytest subprocess × 4 groups        │                               │
│   │  Output: pass/fail per group         │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 8: Push & Merge Request        │                               │
│   │  git push → gh pr create            │                               │
│   │  Auto-merge if score >= threshold    │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 9: Update Documentation        │                               │
│   │  Re-analyze → write docs → commit    │                               │
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────┐                               │
│   │  Step 10: Log & Confirm              │                               │
│   │  Save JSON log + persist to Postgres │                               │
│   └──────────────────────────────────────┘                               │
└──────────────────────────────────────────────────────────────────────────┘
```

## 2. Request Flow

```
Client (curl / HTTP)
  │
  │  POST /pipeline/start
  │  {"repo_path": "/path/to/repo"}
  │
  ▼
┌──────────────────────────────────┐
│         FastAPI Router           │
│  app.py route handlers           │
│  (no auth middleware)            │
└──────────────┬───────────────────┘
               │
        ┌──────┴──────┐
        │             │
        ▼             ▼
  Temporal         In-Process
  Connected?       Fallback
        │             │
        ▼             ▼
  ┌───────────┐  ┌──────────────────────┐
  │ start_    │  │ _run_pipeline_       │
  │ workflow  │  │ inprocess()          │
  │ (async)   │  │ (run_in_executor)    │
  └─────┬─────┘  └──────────┬───────────┘
        │                   │
        ▼                   ▼
  ┌───────────────────────────────────┐
  │     Activity Execution            │
  │                                   │
  │  analyze_repo ─► suggest ─►      │
  │  execute_changes ─► review ─►    │
  │  generate_tests ─► run_tests ─►  │
  │  push + PR + merge ─► update_docs│
  └───────────────────────────────────┘
               │
     ┌─────────┼─────────┐
     │         │         │
     ▼         ▼         ▼
┌─────────┐ ┌────────┐ ┌─────────────┐
│ OpenAI  │ │ Target │ │ PostgreSQL  │
│ API     │ │ Repo   │ │ + JSON logs │
│ (GPT-4.1│ │ (git)  │ │ (beads)     │
└─────────┘ └────────┘ └─────────────┘
```

## 3. Module Dependency Graph

```
app.py
  ├── config.py (settings)
  ├── features/beads/db.py (init_db, pipeline run CRUD, bead queries)
  ├── workflows/pipeline.py (CodeImprovementPipeline)
  │     ├── activities/analyze.py
  │     │     ├── utils/llm.py (chat, chat_json)
  │     │     └── utils/repo_scanner.py (scan_repo, build_tree_string, build_file_summary)
  │     ├── activities/suggest.py
  │     │     ├── utils/llm.py
  │     │     └── utils/repo_scanner.py
  │     ├── activities/execute_changes.py
  │     │     ├── utils/llm.py
  │     │     └── utils/repo_scanner.py
  │     ├── activities/review.py
  │     │     ├── utils/llm.py
  │     │     └── utils/repo_scanner.py
  │     ├── activities/test_gen.py
  │     │     ├── utils/llm.py
  │     │     └── utils/repo_scanner.py
  │     ├── activities/test_run.py (subprocess: pytest)
  │     ├── activities/git_ops.py (subprocess: git, gh)
  │     ├── activities/update_docs.py
  │     │     └── activities/analyze.py (re-uses analyze)
  │     ├── features/beads/tracker.py
  │     │     ├── features/beads/models.py (Bead, BeadStatus)
  │     │     └── features/beads/db.py (upsert_bead)
  │     └── config.py
  └── activities/scaffold.py (standalone scaffold endpoint)
        ├── utils/llm.py
        └── utils/repo_scanner.py

worker.py
  ├── config.py
  ├── workflows/pipeline.py (CodeImprovementPipeline)
  └── activities/* (all activities registered)

utils/llm.py
  ├── openai (OpenAI client)
  └── config.py (OPENAI_API_KEY, OPENAI_MODEL)

utils/repo_scanner.py
  └── config.py (ANALYZABLE_EXTENSIONS, MAX_FILE_SIZE, MAX_CONTEXT_CHARS)

features/beads/db.py
  ├── psycopg2 (Postgres driver)
  └── config.py (DATABASE_URL)

features/beads/models.py
  └── (no internal dependencies — pure dataclasses)

models/schemas.py
  └── features/beads/models.py (re-exports Bead, BeadStatus)
```

## 4. LLM Call Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     LLM Interactions                         │
│                                                             │
│  Activity              Call Type     Max Tokens   Calls     │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  analyze_repo          chat()        8192         3         │
│    ├── specification.md generation                          │
│    ├── graph.md generation                                  │
│    └── architecture.md generation                           │
│                                                             │
│  suggest_improvements  chat_json()   4096         4         │
│    ├── features improvements                                │
│    ├── security improvements                                │
│    ├── compliance improvements                              │
│    └── integration improvements                             │
│                                                             │
│  execute_changes       chat() /      4096-8192    N         │
│                        chat_json()               (per change)│
│    ├── _generate_new_file → chat()                          │
│    └── _modify_file → chat_json()                           │
│                                                             │
│  review_changes        chat_json()   4096         1         │
│    └── scored review with issues                            │
│                                                             │
│  generate_tests        chat_json()   8192         4         │
│    ├── features test file                                   │
│    ├── security test file                                   │
│    ├── compliance test file                                 │
│    └── integration test file                                │
│                                                             │
│  scaffold_repo         chat() /      2000-6000    varies    │
│                        chat_json()   (per file)             │
│    ├── README.md, CONTRIBUTING.md                           │
│    ├── specification.md, architecture.md, graph.md          │
│    ├── CI workflow, Makefile                                │
│    └── test scaffold                                        │
│                                                             │
│  update_docs           (delegates to analyze_repo)          │
│                                                             │
│  Total per pipeline run: ~12+ LLM calls (minimum)          │
└─────────────────────────────────────────────────────────────┘
```

## 5. Bead Lifecycle State Diagram

```
                  ┌──────────────┐
   create()       │              │
  ────────────►   │   PENDING    │
                  │              │
                  └──────┬───────┘
                         │
                  start()│
                         │
                         ▼
                  ┌──────────────┐
                  │              │
                  │   RUNNING    │
                  │              │
                  └──────┬───────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
    complete()│   fail() │   skip() │
              │          │          │
              ▼          ▼          ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │          │ │          │ │          │
        │COMPLETED │ │  FAILED  │ │ SKIPPED  │
        │          │ │          │ │          │
        └──────────┘ └──────────┘ └──────────┘

  Each transition persists to Postgres (if available).
  Timing is recorded: started_at, completed_at, duration_sec.
```

## 6. Data Persistence Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    Data Persistence                            │
│                                                              │
│   BeadTracker                                                │
│      │                                                       │
│      │  every state change                                   │
│      ├──────────────────────────────►  Postgres              │
│      │   upsert_bead(run_id, bead)     ┌──────────────┐     │
│      │                                 │ beads table   │     │
│      │                                 │ (id, run_id,  │     │
│      │                                 │  status, etc) │     │
│      │                                 └──────────────┘     │
│      │                                                       │
│      │                                 ┌──────────────┐     │
│      │   upsert_pipeline_run(record)   │pipeline_runs │     │
│      ├──────────────────────────────►  │ (run_id,     │     │
│      │                                 │  status,     │     │
│      │                                 │  JSONB cols) │     │
│      │                                 └──────────────┘     │
│      │                                                       │
│      │                                                       │
│   Pipeline Completion                                        │
│      │                                                       │
│      │  JSON dump                      ┌──────────────┐     │
│      └──────────────────────────────►  │ pipeline_runs│     │
│                                        │ /{run_id}.json│    │
│                                        └──────────────┘     │
│                                                              │
│   Query Path:                                                │
│   GET /pipeline/{id}  →  Postgres  →  JSON file  →  Temporal│
│   GET /beads/{run_id} →  Postgres (with status/category     │
│                          filters)                            │
└──────────────────────────────────────────────────────────────┘
```

## 7. Git Operations Flow

```
┌─────────────────────────────────────────────────────────┐
│                 Git Operations Sequence                   │
│                                                         │
│   Target Repository                                     │
│   │                                                     │
│   │  Step 4: create_branch                              │
│   │  ┌────────────────────────────┐                     │
│   │  │ git checkout -b            │                     │
│   │  │ repo-pilot/{run_id}        │                     │
│   │  └────────────┬───────────────┘                     │
│   │               │                                     │
│   │  Step 4: execute_changes                            │
│   │  ┌────────────────────────────┐                     │
│   │  │ LLM generates code        │                     │
│   │  │ Write files to disk       │                     │
│   │  └────────────┬───────────────┘                     │
│   │               │                                     │
│   │  Step 4: commit_changes                             │
│   │  ┌────────────────────────────┐                     │
│   │  │ git add -A                │                     │
│   │  │ git commit -m "..."       │                     │
│   │  └────────────┬───────────────┘                     │
│   │               │                                     │
│   │  Step 7: commit tests                               │
│   │  ┌────────────────────────────┐                     │
│   │  │ git add -A                │                     │
│   │  │ git commit -m "..."       │                     │
│   │  └────────────┬───────────────┘                     │
│   │               │                                     │
│   │  Step 8: push_branch                                │
│   │  ┌────────────────────────────┐                     │
│   │  │ git push -u origin        │                     │
│   │  │ repo-pilot/{run_id}       │                     │
│   │  └────────────┬───────────────┘                     │
│   │               │                                     │
│   │  Step 8: create_merge_request                       │
│   │  ┌────────────────────────────┐                     │
│   │  │ gh pr create              │                     │
│   │  │ --title --body --base main│                     │
│   │  └────────────┬───────────────┘                     │
│   │               │                                     │
│   │  Step 8: auto_merge (conditional)                   │
│   │  ┌────────────────────────────┐                     │
│   │  │ IF score >= threshold:     │                     │
│   │  │   gh pr merge --merge     │                     │
│   │  │   --delete-branch         │                     │
│   │  │ ELSE: blocked             │                     │
│   │  └────────────┬───────────────┘                     │
│   │               │                                     │
│   │  Step 8/9: checkout_main (if merged)                │
│   │  ┌────────────────────────────┐                     │
│   │  │ git checkout main         │                     │
│   │  │ git pull origin main      │                     │
│   │  └────────────┬───────────────┘                     │
│   │               │                                     │
│   │  Step 9: commit + push docs                         │
│   │  ┌────────────────────────────┐                     │
│   │  │ git commit -m "..."       │                     │
│   │  │ git push origin main      │                     │
│   │  └────────────────────────────┘                     │
│   │                                                     │
└───┴─────────────────────────────────────────────────────┘
```

## 8. Improvement Category Taxonomy

```
                      Improvements
                          │
          ┌───────────────┼───────────────┬──────────────┐
          │               │               │              │
          ▼               ▼               ▼              ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
    │          │   │          │   │          │   │          │
    │ FEATURES │   │ SECURITY │   │COMPLIANCE│   │INTEGRA-  │
    │          │   │          │   │          │   │TION      │
    └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘
         │              │              │              │
    Error handling  Input         HIPAA (PHI)    OpenTelemetry
    New endpoints   validation    PCI-DSS        Structured
    Data models     Rate          FDA 21 CFR     logging
    Caching         limiting      Part 11        Health checks
    Pagination      Auth/AuthZ    State regs     Docker
    Retry logic     Secrets       Data           CI/CD
    Logging         CORS          retention      API versioning
    Config          Secure        Consent        Webhooks
    UX              headers       ADA/WCAG       Event-driven
         │              │              │              │
         └──────────────┴──────────────┴──────────────┘
                               │
                    Each category produces
                    2-4 improvements with:
                    • title, description
                    • priority (high/medium/low)
                    • files_affected
                    • changes [{file, description, code_hint}]
```

## 9. API Route Map

```
                             /
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
       /health          /pipeline          /scaffold
       (GET)                │               (POST)
       [no auth]            │
                            │
                 ┌──────────┼──────────┐
                 │          │          │
              /start     /runs    /{run_id}
              (POST)     (GET)      (GET)
                         ?status    │
                         ?limit     │
                                    │
          ┌─────────────────────────────────────┐
          │                                     │
       /beads                               /bead
          │                                 /{bead_id}
    /{run_id}                                (GET)
     (GET)
     ?status
     ?category
          │
    /{run_id}/summary
     (GET)
```

## 10. Temporal Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Temporal Architecture                        │
│                                                             │
│   ┌──────────────┐         ┌──────────────────────┐        │
│   │ FastAPI App   │         │  Temporal Server     │        │
│   │ (app.py)      │────────►│  (localhost:7233)    │        │
│   │               │ start   │                      │        │
│   │ temporal_     │ workflow│  Stores workflow     │        │
│   │ client.start_ │         │  state durably       │        │
│   │ workflow()    │         └──────────┬───────────┘        │
│   └──────────────┘                    │                     │
│                                       │ dispatches          │
│                                       │ activities          │
│                                       ▼                     │
│                          ┌──────────────────────┐           │
│                          │  Temporal Worker     │           │
│                          │  (worker.py)          │           │
│                          │                      │           │
│                          │  Task Queue:         │           │
│                          │  "repo-pilot-queue"  │           │
│                          │                      │           │
│                          │  Registered:         │           │
│                          │  • 1 workflow class  │           │
│                          │  • 16 activities     │           │
│                          └──────────┬───────────┘           │
│                                     │                       │
│                          ┌──────────┴───────────┐           │
│                          │  Activity Timeouts   │           │
│                          │                      │           │
│                          │  analyze:     5 min  │           │
│                          │  suggest:     5 min  │           │
│                          │  execute:    10 min  │           │
│                          │  review:      5 min  │           │
│                          │  test_gen:   10 min  │           │
│                          │  test_run:   10 min  │           │
│                          │  git ops:  1-2 min   │           │
│                          │  update_docs: 5 min  │           │
│                          └──────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

## 11. Database Schema

```
┌─────────────────────────────────────────────────────┐
│                  pipeline_runs                       │
├─────────────────────────────────────────────────────┤
│  run_id          TEXT          PK                    │
│  target_repo     TEXT          NOT NULL              │
│  branch_name     TEXT                                │
│  status          TEXT          NOT NULL DEFAULT      │
│                               'pending'              │
│  started_at      TIMESTAMPTZ                         │
│  completed_at    TIMESTAMPTZ                         │
│  duration_sec    DOUBLE PRECISION                    │
│  error           TEXT                                │
│  improvements    JSONB         DEFAULT '[]'          │
│  code_changes    JSONB         DEFAULT '[]'          │
│  review          JSONB         DEFAULT '{}'          │
│  test_results    JSONB         DEFAULT '[]'          │
│  merge_result    JSONB         DEFAULT '{}'          │
│  docs_updated    JSONB         DEFAULT '[]'          │
│  repo_analysis   JSONB         DEFAULT '{}'          │
│  log_file        TEXT                                │
│  created_at      TIMESTAMPTZ   DEFAULT now()         │
├─────────────────────────────────────────────────────┤
│  INDEX: idx_pipeline_runs_status (status)            │
│  1 ──────── * beads                                  │
└─────────────────────────────────────────────────────┘
               │ ON DELETE CASCADE
               │
               ▼
┌─────────────────────────────────────────────────────┐
│                       beads                          │
├─────────────────────────────────────────────────────┤
│  id              TEXT          PK                    │
│  run_id          TEXT          FK NOT NULL            │
│  name            TEXT          NOT NULL              │
│  category        TEXT          NOT NULL              │
│  status          TEXT          NOT NULL DEFAULT      │
│                               'pending'              │
│  started_at      TIMESTAMPTZ                         │
│  completed_at    TIMESTAMPTZ                         │
│  duration_sec    DOUBLE PRECISION                    │
│  input_summary   TEXT          DEFAULT ''            │
│  output_summary  TEXT          DEFAULT ''            │
│  error           TEXT                                │
│  metadata        JSONB         DEFAULT '{}'          │
│  created_at      TIMESTAMPTZ   DEFAULT now()         │
│  updated_at      TIMESTAMPTZ   DEFAULT now()         │
├─────────────────────────────────────────────────────┤
│  INDEX: idx_beads_run_id (run_id)                    │
│  INDEX: idx_beads_status (status)                    │
│  INDEX: idx_beads_category (category)                │
└─────────────────────────────────────────────────────┘
```
