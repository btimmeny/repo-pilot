"""
Postgres backing store for beads and pipeline runs.

Tables:
  pipeline_runs  — one row per pipeline execution
  beads          — one row per bead, FK to pipeline_runs

Every bead state change (create/start/complete/fail/skip) is persisted
immediately so the audit trail survives crashes.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras

import config

log = logging.getLogger(__name__)

# ── Connection ────────────────────────────────────────────────────────

_pool: list[Any] = []


def _get_conn():
    """Get a Postgres connection (simple single-connection reuse)."""
    if _pool:
        conn = _pool[0]
        try:
            conn.isolation_level  # cheap liveness check
            return conn
        except Exception:
            _pool.clear()

    conn = psycopg2.connect(config.DATABASE_URL)
    conn.autocommit = True
    _pool.append(conn)
    return conn


@contextmanager
def get_cursor():
    """Yield a dict cursor, handling errors gracefully."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
    finally:
        cur.close()


# ── Schema ────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          TEXT PRIMARY KEY,
    target_repo     TEXT NOT NULL,
    branch_name     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_sec    DOUBLE PRECISION,
    error           TEXT,
    improvements    JSONB DEFAULT '[]'::jsonb,
    code_changes    JSONB DEFAULT '[]'::jsonb,
    review          JSONB DEFAULT '{}'::jsonb,
    test_results    JSONB DEFAULT '[]'::jsonb,
    merge_result    JSONB DEFAULT '{}'::jsonb,
    docs_updated    JSONB DEFAULT '[]'::jsonb,
    repo_analysis   JSONB DEFAULT '{}'::jsonb,
    log_file        TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS beads (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_sec    DOUBLE PRECISION,
    input_summary   TEXT DEFAULT '',
    output_summary  TEXT DEFAULT '',
    error           TEXT,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_beads_run_id ON beads(run_id);
CREATE INDEX IF NOT EXISTS idx_beads_status ON beads(status);
CREATE INDEX IF NOT EXISTS idx_beads_category ON beads(category);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
"""


def init_db():
    """Create tables if they don't exist."""
    try:
        with get_cursor() as cur:
            cur.execute(SCHEMA_SQL)
        log.info("Database schema initialized")
    except Exception as e:
        log.error("Failed to initialize database: %s", e)
        raise


# ── Pipeline Run CRUD ─────────────────────────────────────────────────

def upsert_pipeline_run(run: dict) -> None:
    """Insert or update a pipeline run record."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO pipeline_runs (
                run_id, target_repo, branch_name, status,
                started_at, completed_at, duration_sec, error,
                improvements, code_changes, review, test_results,
                merge_result, docs_updated, repo_analysis, log_file
            ) VALUES (
                %(run_id)s, %(target_repo)s, %(branch_name)s, %(status)s,
                %(started_at)s, %(completed_at)s, %(duration_sec)s, %(error)s,
                %(improvements)s, %(code_changes)s, %(review)s, %(test_results)s,
                %(merge_result)s, %(docs_updated)s, %(repo_analysis)s, %(log_file)s
            )
            ON CONFLICT (run_id) DO UPDATE SET
                status = EXCLUDED.status,
                completed_at = EXCLUDED.completed_at,
                duration_sec = EXCLUDED.duration_sec,
                error = EXCLUDED.error,
                improvements = EXCLUDED.improvements,
                code_changes = EXCLUDED.code_changes,
                review = EXCLUDED.review,
                test_results = EXCLUDED.test_results,
                merge_result = EXCLUDED.merge_result,
                docs_updated = EXCLUDED.docs_updated,
                repo_analysis = EXCLUDED.repo_analysis,
                log_file = EXCLUDED.log_file
        """, {
            "run_id": run.get("run_id"),
            "target_repo": run.get("target_repo", ""),
            "branch_name": run.get("branch_name", ""),
            "status": run.get("status", "pending"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "duration_sec": run.get("duration_sec"),
            "error": run.get("error"),
            "improvements": json.dumps(run.get("improvements", [])),
            "code_changes": json.dumps(run.get("code_changes", [])),
            "review": json.dumps(run.get("review", {})),
            "test_results": json.dumps(run.get("test_results", [])),
            "merge_result": json.dumps(run.get("merge_result", {})),
            "docs_updated": json.dumps(run.get("docs_updated", [])),
            "repo_analysis": json.dumps(run.get("repo_analysis", {})),
            "log_file": run.get("log_file", ""),
        })


def get_pipeline_run(run_id: str) -> dict | None:
    """Fetch a pipeline run by ID."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM pipeline_runs WHERE run_id = %s", (run_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_pipeline_runs(limit: int = 50, status: str | None = None) -> list[dict]:
    """List pipeline runs, newest first."""
    with get_cursor() as cur:
        if status:
            cur.execute(
                "SELECT * FROM pipeline_runs WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM pipeline_runs ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        return [dict(row) for row in cur.fetchall()]


# ── Bead CRUD ─────────────────────────────────────────────────────────

def upsert_bead(run_id: str, bead: dict) -> None:
    """Insert or update a bead. Called on every state change."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO beads (
                id, run_id, name, category, status,
                started_at, completed_at, duration_sec,
                input_summary, output_summary, error, metadata
            ) VALUES (
                %(id)s, %(run_id)s, %(name)s, %(category)s, %(status)s,
                %(started_at)s, %(completed_at)s, %(duration_sec)s,
                %(input_summary)s, %(output_summary)s, %(error)s, %(metadata)s
            )
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                duration_sec = EXCLUDED.duration_sec,
                output_summary = EXCLUDED.output_summary,
                error = EXCLUDED.error,
                metadata = EXCLUDED.metadata,
                updated_at = now()
        """, {
            "id": bead.get("id"),
            "run_id": run_id,
            "name": bead.get("name", ""),
            "category": bead.get("category", ""),
            "status": bead.get("status", "pending"),
            "started_at": bead.get("started_at"),
            "completed_at": bead.get("completed_at"),
            "duration_sec": bead.get("duration_sec"),
            "input_summary": bead.get("input_summary", ""),
            "output_summary": bead.get("output_summary", ""),
            "error": bead.get("error"),
            "metadata": json.dumps(bead.get("metadata", {})),
        })


def get_beads_for_run(run_id: str) -> list[dict]:
    """Fetch all beads for a pipeline run, ordered by creation time."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM beads WHERE run_id = %s ORDER BY created_at ASC",
            (run_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_bead(bead_id: str) -> dict | None:
    """Fetch a single bead by ID."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM beads WHERE id = %s", (bead_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_beads_by_status(status: str, run_id: str | None = None) -> list[dict]:
    """Fetch beads filtered by status, optionally scoped to a run."""
    with get_cursor() as cur:
        if run_id:
            cur.execute(
                "SELECT * FROM beads WHERE status = %s AND run_id = %s ORDER BY created_at ASC",
                (status, run_id),
            )
        else:
            cur.execute(
                "SELECT * FROM beads WHERE status = %s ORDER BY created_at DESC LIMIT 100",
                (status,),
            )
        return [dict(row) for row in cur.fetchall()]


def get_beads_by_category(category: str, run_id: str | None = None) -> list[dict]:
    """Fetch beads filtered by category."""
    with get_cursor() as cur:
        if run_id:
            cur.execute(
                "SELECT * FROM beads WHERE category = %s AND run_id = %s ORDER BY created_at ASC",
                (category, run_id),
            )
        else:
            cur.execute(
                "SELECT * FROM beads WHERE category = %s ORDER BY created_at DESC LIMIT 100",
                (category,),
            )
        return [dict(row) for row in cur.fetchall()]


def get_bead_summary(run_id: str) -> dict:
    """Get an aggregate summary of beads for a run."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT
                count(*) as total_beads,
                count(*) FILTER (WHERE status = 'completed') as completed,
                count(*) FILTER (WHERE status = 'failed') as failed,
                count(*) FILTER (WHERE status = 'running') as running,
                count(*) FILTER (WHERE status = 'pending') as pending,
                count(*) FILTER (WHERE status = 'skipped') as skipped,
                coalesce(sum(duration_sec), 0) as total_duration_sec
            FROM beads WHERE run_id = %s
        """, (run_id,))
        row = cur.fetchone()
        return dict(row) if row else {}
