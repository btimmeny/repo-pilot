"""
FastAPI application — REST API for Repo Pilot.

Endpoints:
  POST /pipeline/start    — Start a code improvement pipeline run
  GET  /pipeline/{run_id} — Get pipeline run status/results
  GET  /pipeline/runs     — List all pipeline runs
  GET  /health            — Health check
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
from temporalio.client import Client
from workflows.pipeline import CodeImprovementPipeline
from features.beads import db as bead_db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

temporal_client: Client | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global temporal_client
    # Initialize Postgres
    try:
        bead_db.init_db()
        log.info("Postgres database initialized")
    except Exception as e:
        log.warning("Could not connect to Postgres: %s (beads will be in-memory only)", e)
    # Connect to Temporal
    try:
        temporal_client = await Client.connect(config.TEMPORAL_HOST)
        log.info("Connected to Temporal at %s", config.TEMPORAL_HOST)
    except Exception as e:
        log.warning("Could not connect to Temporal: %s (pipeline will run in-process)", e)
        temporal_client = None
    yield


app = FastAPI(
    title="Repo Pilot",
    description="Autonomous code improvement pipeline with Temporal orchestration and bead tracking",
    version="1.0.0",
    lifespan=lifespan,
)


class PipelineStartRequest(BaseModel):
    repo_path: str = str(config.TARGET_REPO_PATH)


class PipelineStartResponse(BaseModel):
    run_id: str
    status: str
    message: str


# ── Health ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "repo-pilot",
        "temporal_connected": temporal_client is not None,
    }


# ── Scaffold ─────────────────────────────────────────────────────────

class ScaffoldRequest(BaseModel):
    repo_path: str = str(config.TARGET_REPO_PATH)
    commit: bool = True  # auto-commit generated files


@app.post("/scaffold")
async def scaffold_repository(req: ScaffoldRequest):
    """Scaffold best-practice files for a repository."""
    repo_path = req.repo_path
    if not Path(repo_path).is_dir():
        raise HTTPException(status_code=400, detail=f"Repository not found: {repo_path}")

    from activities.scaffold import scaffold_repo
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, scaffold_repo, repo_path)

    # Auto-commit if requested and files were created
    if req.commit and result["created"]:
        from activities.git_ops import commit_changes
        try:
            await loop.run_in_executor(
                None, commit_changes, repo_path,
                f"repo-pilot: scaffold {len(result['created'])} best-practice files",
            )
            result["committed"] = True
        except Exception as e:
            result["committed"] = False
            result["commit_error"] = str(e)

    return result


# ── Pipeline ──────────────────────────────────────────────────────────

@app.post("/pipeline/start", response_model=PipelineStartResponse)
async def start_pipeline(req: PipelineStartRequest):
    """Start a code improvement pipeline run on the target repository."""
    repo_path = req.repo_path

    if not Path(repo_path).is_dir():
        raise HTTPException(status_code=400, detail=f"Repository not found: {repo_path}")

    if temporal_client:
        # Start via Temporal workflow
        from datetime import datetime, timezone
        import uuid
        run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

        handle = await temporal_client.start_workflow(
            CodeImprovementPipeline.run,
            repo_path,
            id=run_id,
            task_queue=config.TEMPORAL_TASK_QUEUE,
        )
        return PipelineStartResponse(
            run_id=run_id,
            status="started",
            message=f"Pipeline started via Temporal. Workflow ID: {run_id}",
        )
    else:
        # Run in-process (no Temporal server)
        run_id = await _run_pipeline_inprocess(repo_path)
        return PipelineStartResponse(
            run_id=run_id,
            status="completed",
            message=f"Pipeline ran in-process (no Temporal). Run ID: {run_id}",
        )


@app.get("/pipeline/runs")
async def list_pipeline_runs(status: str | None = None, limit: int = 50):
    """List all pipeline runs."""
    # Try Postgres first
    try:
        runs = bead_db.list_pipeline_runs(limit=limit, status=status)
        return {"runs": [_serialize(r) for r in runs]}
    except Exception:
        pass

    # Fallback: JSON files
    config.PIPELINE_RUNS_DIR.mkdir(exist_ok=True)
    runs = []
    for log_file in sorted(config.PIPELINE_RUNS_DIR.glob("*.json"), reverse=True):
        try:
            with open(log_file) as f:
                data = json.load(f)
            runs.append({
                "run_id": data.get("run_id"),
                "status": data.get("status"),
                "started_at": data.get("started_at"),
                "duration_sec": data.get("duration_sec"),
                "improvements": len(data.get("improvements", [])),
            })
        except Exception:
            pass
    return {"runs": runs}


@app.get("/pipeline/{run_id}")
async def get_pipeline_run(run_id: str):
    """Get the results of a pipeline run."""
    # Check Postgres first
    try:
        row = bead_db.get_pipeline_run(run_id)
        if row:
            row["beads"] = bead_db.get_beads_for_run(run_id)
            row["bead_summary"] = bead_db.get_bead_summary(run_id)
            return _serialize(row)
    except Exception:
        pass

    # Fallback: check local log file
    log_file = config.PIPELINE_RUNS_DIR / f"{run_id}.json"
    if log_file.exists():
        with open(log_file) as f:
            return json.load(f)

    # Check Temporal if connected
    if temporal_client:
        try:
            handle = temporal_client.get_workflow_handle(run_id)
            desc = await handle.describe()
            result = None
            if desc.status.name == "COMPLETED":
                result = await handle.result()
            return {
                "run_id": run_id,
                "temporal_status": desc.status.name,
                "result": result,
            }
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


# ── Bead query endpoints ──────────────────────────────────────────────

@app.get("/beads/{run_id}")
async def get_beads(run_id: str, status: str | None = None, category: str | None = None):
    """Get all beads for a pipeline run, with optional filters."""
    try:
        if status:
            beads = bead_db.get_beads_by_status(status, run_id=run_id)
        elif category:
            beads = bead_db.get_beads_by_category(category, run_id=run_id)
        else:
            beads = bead_db.get_beads_for_run(run_id)
        return {"run_id": run_id, "beads": [_serialize(b) for b in beads], "count": len(beads)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/beads/{run_id}/summary")
async def get_bead_summary(run_id: str):
    """Get an aggregate summary of beads for a run."""
    try:
        summary = bead_db.get_bead_summary(run_id)
        return {"run_id": run_id, **_serialize(summary)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/bead/{bead_id}")
async def get_single_bead(bead_id: str):
    """Get a single bead by ID."""
    try:
        bead = bead_db.get_bead(bead_id)
        if not bead:
            raise HTTPException(status_code=404, detail=f"Bead not found: {bead_id}")
        return _serialize(bead)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


def _serialize(obj: Any) -> Any:
    """Make a dict JSON-serializable (handle datetimes, Decimals, etc)."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


# ── In-process pipeline (fallback when Temporal is not available) ─────

async def _run_pipeline_inprocess(repo_path: str) -> str:
    """Run the full pipeline in-process without Temporal."""
    import time
    import uuid
    from datetime import datetime, timezone

    from activities.analyze import analyze_repo
    from activities.suggest import suggest_improvements
    from activities.execute_changes import execute_changes
    from activities.review import review_changes
    from activities.test_gen import generate_tests
    from activities.test_run import run_tests
    from activities.git_ops import (
        create_branch, commit_changes, push_branch,
        create_merge_request, auto_merge, checkout_main,
    )
    from activities.update_docs import update_docs
    from features.beads.tracker import BeadTracker

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    branch_name = f"{config.IMPROVEMENT_BRANCH_PREFIX}/{run_id}"
    tracker = BeadTracker(run_id)
    pipeline_start = time.monotonic()

    run_record = {
        "run_id": run_id,
        "target_repo": repo_path,
        "branch_name": branch_name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }

    # Persist initial run record to Postgres
    try:
        bead_db.upsert_pipeline_run(run_record)
    except Exception as e:
        log.warning("Could not persist run to Postgres: %s", e)

    loop = asyncio.get_running_loop()

    try:
        # Step 1: Analyze
        bead = tracker.create("Analyze Repository", "analysis")
        tracker.start(bead)
        analysis = await loop.run_in_executor(None, analyze_repo, repo_path)
        tracker.complete(bead, output_summary=f"{analysis['stats']['total_files']} files scanned")
        run_record["repo_analysis"] = {"stats": analysis["stats"]}

        # Write initial docs
        repo = Path(repo_path)
        docs_dir = repo / "docs"
        docs_dir.mkdir(exist_ok=True)
        for name, key in [("specification.md", "specification"), ("graph.md", "graph"), ("architecture.md", "architecture")]:
            content = analysis.get(key, "")
            if content:
                (docs_dir / name).write_text(content)

        # Step 2: Suggest Improvements
        bead = tracker.create("Suggest Improvements", "suggestions")
        tracker.start(bead)
        improvements = await loop.run_in_executor(None, suggest_improvements, repo_path)
        tracker.complete(bead, output_summary=f"{len(improvements)} improvements")
        run_record["improvements"] = improvements

        # Step 3: Log tasks as beads
        for imp in improvements:
            task_bead = tracker.create(f"Task: {imp['title']}", imp["category"])
            task_bead.metadata["improvement_id"] = imp["id"]

        # Step 4: Create branch + execute changes
        bead_branch = tracker.create("Create Branch", "git")
        tracker.start(bead_branch)
        await loop.run_in_executor(None, create_branch, repo_path, branch_name)
        tracker.complete(bead_branch, output_summary=branch_name)

        bead = tracker.create("Execute Code Changes", "execution")
        tracker.start(bead)
        applied_changes = await loop.run_in_executor(None, execute_changes, repo_path, improvements)
        applied_count = sum(1 for c in applied_changes if c["status"] == "applied")
        tracker.complete(bead, output_summary=f"{applied_count} applied")
        run_record["code_changes"] = applied_changes

        # Mark task beads
        for tb in tracker.beads:
            imp_id = tb.metadata.get("improvement_id")
            if imp_id:
                applied = any(c["improvement_id"] == imp_id and c["status"] == "applied" for c in applied_changes)
                if applied:
                    tracker.complete(tb, output_summary="Applied")
                else:
                    tracker.skip(tb, "No changes applied")

        # Commit
        await loop.run_in_executor(None, commit_changes, repo_path,
                                   f"repo-pilot: apply {applied_count} improvements ({run_id})")

        # Step 5: Code Review
        bead = tracker.create("Code Review", "review")
        tracker.start(bead)
        review = await loop.run_in_executor(None, review_changes, repo_path, applied_changes)
        score = review.get("overall_score", 0)
        tracker.complete(bead, output_summary=f"Score: {score}/10")
        run_record["review"] = review

        # Step 6: Generate Tests
        bead = tracker.create("Generate Tests", "testing")
        tracker.start(bead)
        test_files = await loop.run_in_executor(None, generate_tests, repo_path, improvements, applied_changes)
        tracker.complete(bead, output_summary=f"{sum(t['test_count'] for t in test_files)} tests")
        run_record["tests_generated"] = [{"group": t["group"], "file": t["file"], "test_count": t["test_count"]} for t in test_files]

        # Step 7: Execute Tests
        bead = tracker.create("Execute Tests", "testing")
        tracker.start(bead)
        test_results = await loop.run_in_executor(None, run_tests, repo_path, test_files)
        total_passed = sum(r["passed"] for r in test_results)
        total_failed = sum(r["failed"] for r in test_results)
        tracker.complete(bead, output_summary=f"{total_passed} passed, {total_failed} failed")
        run_record["test_results"] = test_results

        # Commit tests
        await loop.run_in_executor(None, commit_changes, repo_path,
                                   f"repo-pilot: add test suite ({run_id})")

        # Step 8: Push + PR + Auto-merge
        bead = tracker.create("Push & Merge", "git")
        tracker.start(bead)
        await loop.run_in_executor(None, push_branch, repo_path, branch_name)

        pr_body = (
            f"## Repo Pilot — Automated Improvements\n\n"
            f"**Run ID:** `{run_id}`\n"
            f"**Improvements:** {applied_count}\n"
            f"**Review Score:** {score}/10\n"
            f"**Tests:** {total_passed} passed, {total_failed} failed\n"
        )
        pr_result = await loop.run_in_executor(
            None, create_merge_request, repo_path, branch_name,
            f"repo-pilot: {applied_count} improvements ({run_id})", pr_body,
        )

        merge_result = await loop.run_in_executor(None, auto_merge, repo_path, score)
        tracker.complete(bead, output_summary=f"PR: {pr_result.get('status')}, Merge: {merge_result['status']}")
        run_record["merge_result"] = {**pr_result, **merge_result}

        if merge_result["status"] == "merged":
            await loop.run_in_executor(None, checkout_main, repo_path)

        # Step 9: Update docs
        bead = tracker.create("Update Documentation", "documentation")
        tracker.start(bead)
        updated_docs = await loop.run_in_executor(None, update_docs, repo_path)
        tracker.complete(bead, output_summary=f"Updated {len(updated_docs)} docs")
        run_record["docs_updated"] = updated_docs

        await loop.run_in_executor(None, commit_changes, repo_path,
                                   f"repo-pilot: update docs ({run_id})")

        if merge_result["status"] == "merged":
            from activities.git_ops import _git
            await loop.run_in_executor(None, _git, repo_path, "push", "origin", "main")

        run_record["status"] = "completed"

    except Exception as e:
        log.error("Pipeline failed: %s", e, exc_info=True)
        run_record["status"] = "failed"
        run_record["error"] = str(e)

    # Finalize
    run_record["completed_at"] = datetime.now(timezone.utc).isoformat()
    run_record["duration_sec"] = round(time.monotonic() - pipeline_start, 2)
    run_record["beads"] = tracker.to_list()
    run_record["bead_summary"] = tracker.summary()

    # Save log (JSON file)
    config.PIPELINE_RUNS_DIR.mkdir(exist_ok=True)
    log_path = config.PIPELINE_RUNS_DIR / f"{run_id}.json"
    with open(log_path, "w") as f:
        json.dump(run_record, f, indent=2, default=str)
    run_record["log_file"] = str(log_path)

    # Persist final run record to Postgres
    try:
        bead_db.upsert_pipeline_run(run_record)
    except Exception as e:
        log.warning("Could not persist final run to Postgres: %s", e)

    log.info("Pipeline %s complete in %.1fs — %s", run_id, run_record["duration_sec"], run_record["status"])
    return run_id
