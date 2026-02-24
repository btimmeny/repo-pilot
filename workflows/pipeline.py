"""
Temporal Workflow: Code Improvement Pipeline

Orchestrates the full pipeline:
  1. Analyze repo → specification.md, graph.md, architecture.md
  2. Suggest improvements (features, security, compliance, integration)
  3. Log tasks as beads
  4. Execute code changes
  5. Code review with scoring
  6. Generate tests (4 groups)
  7. Execute tests
  8. Create merge request (auto-merge based on score)
  9. Update documentation
  10. Final logging and confirm done
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
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
    from beads.tracker import BeadTracker
    import config

log = logging.getLogger(__name__)


@workflow.defn
class CodeImprovementPipeline:
    """
    Temporal workflow that runs the full code improvement pipeline.

    Each step is tracked as a "bead" — a discrete, logged unit of work.
    """

    @workflow.run
    async def run(self, repo_path: str) -> dict:
        run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        log.info("Pipeline %s starting for %s", run_id, repo_path)
        pipeline_start = time.monotonic()

        tracker = BeadTracker(run_id)
        branch_name = f"{config.IMPROVEMENT_BRANCH_PREFIX}/{run_id}"
        run_record: dict = {
            "run_id": run_id,
            "target_repo": repo_path,
            "branch_name": branch_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }

        try:
            # ━━ Step 1: Analyze Repo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            bead = tracker.create("Analyze Repository", "analysis",
                                  input_summary=f"Scanning {repo_path}")
            tracker.start(bead)
            analysis = await workflow.execute_activity(
                analyze_repo, args=[repo_path],
                start_to_close_timeout=timedelta(minutes=5),
            )
            tracker.complete(bead, output_summary=f"Generated 3 docs, {analysis['stats']['total_files']} files scanned",
                           metadata={"stats": analysis["stats"]})
            run_record["repo_analysis"] = analysis

            # Write initial docs
            bead_docs = tracker.create("Write Initial Docs", "analysis",
                                       input_summary="Writing specification.md, graph.md, architecture.md")
            tracker.start(bead_docs)
            docs_written = await workflow.execute_activity(
                _write_analysis_docs, args=[repo_path, analysis],
                start_to_close_timeout=timedelta(minutes=1),
            )
            tracker.complete(bead_docs, output_summary=f"Wrote {len(docs_written)} docs")

            # ━━ Step 2: Suggest Improvements ━━━━━━━━━━━━━━━━━━━━━━━━━
            bead = tracker.create("Suggest Improvements", "suggestions",
                                  input_summary="Analyzing for features, security, compliance, integration")
            tracker.start(bead)
            improvements = await workflow.execute_activity(
                suggest_improvements, args=[repo_path],
                start_to_close_timeout=timedelta(minutes=5),
            )
            tracker.complete(bead, output_summary=f"{len(improvements)} improvements suggested",
                           metadata={"count": len(improvements)})
            run_record["improvements"] = improvements

            # ━━ Step 3: Log Tasks as Beads ━━━━━━━━━━━━━━━━━━━━━━━━━━━
            for imp in improvements:
                task_bead = tracker.create(
                    f"Task: {imp['title']}",
                    imp["category"],
                    input_summary=imp["description"],
                )
                task_bead.metadata["improvement_id"] = imp["id"]
                task_bead.metadata["priority"] = imp.get("priority", "medium")
                task_bead.metadata["files"] = imp.get("files_affected", [])

            # ━━ Step 4: Create Branch + Execute Changes ━━━━━━━━━━━━━━
            bead_branch = tracker.create("Create Branch", "git",
                                         input_summary=branch_name)
            tracker.start(bead_branch)
            await workflow.execute_activity(
                create_branch, args=[repo_path, branch_name],
                start_to_close_timeout=timedelta(minutes=1),
            )
            tracker.complete(bead_branch, output_summary=f"Branch: {branch_name}")

            bead = tracker.create("Execute Code Changes", "execution",
                                  input_summary=f"Applying {len(improvements)} improvements")
            tracker.start(bead)
            applied_changes = await workflow.execute_activity(
                execute_changes, args=[repo_path, improvements],
                start_to_close_timeout=timedelta(minutes=10),
            )
            applied_count = sum(1 for c in applied_changes if c["status"] == "applied")
            tracker.complete(bead, output_summary=f"{applied_count}/{len(applied_changes)} changes applied",
                           metadata={"applied": applied_count, "total": len(applied_changes)})
            run_record["code_changes"] = applied_changes

            # Mark task beads as completed
            for tb in tracker.beads:
                imp_id = tb.metadata.get("improvement_id")
                if imp_id:
                    applied = any(c["improvement_id"] == imp_id and c["status"] == "applied"
                                 for c in applied_changes)
                    if applied:
                        tracker.complete(tb, output_summary="Changes applied")
                    else:
                        tracker.skip(tb, reason="No changes applied")

            # Commit changes
            bead_commit = tracker.create("Commit Changes", "git",
                                         input_summary="Committing applied improvements")
            tracker.start(bead_commit)
            commit_result = await workflow.execute_activity(
                commit_changes, args=[repo_path, f"repo-pilot: apply {applied_count} improvements ({run_id})"],
                start_to_close_timeout=timedelta(minutes=1),
            )
            tracker.complete(bead_commit, output_summary=commit_result.get("sha", "no commit"),
                           metadata=commit_result)

            # ━━ Step 5: Code Review ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            bead = tracker.create("Code Review", "review",
                                  input_summary=f"Reviewing {applied_count} changes")
            tracker.start(bead)
            review = await workflow.execute_activity(
                review_changes, args=[repo_path, applied_changes],
                start_to_close_timeout=timedelta(minutes=5),
            )
            score = review.get("overall_score", 0)
            tracker.complete(bead, output_summary=f"Score: {score}/10 — {'PASS' if review.get('passed') else 'FAIL'}",
                           metadata={"score": score, "passed": review.get("passed")})
            run_record["review"] = review

            # ━━ Step 6: Generate Tests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            bead = tracker.create("Generate Tests", "testing",
                                  input_summary="Generating tests in 4 groups")
            tracker.start(bead)
            test_files = await workflow.execute_activity(
                generate_tests, args=[repo_path, improvements, applied_changes],
                start_to_close_timeout=timedelta(minutes=10),
            )
            total_tests = sum(t["test_count"] for t in test_files)
            tracker.complete(bead, output_summary=f"{total_tests} tests in {len(test_files)} groups",
                           metadata={"total_tests": total_tests})
            run_record["tests_generated"] = test_files

            # ━━ Step 7: Execute Tests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            bead = tracker.create("Execute Tests", "testing",
                                  input_summary=f"Running {total_tests} tests")
            tracker.start(bead)
            test_results = await workflow.execute_activity(
                run_tests, args=[repo_path, test_files],
                start_to_close_timeout=timedelta(minutes=10),
            )
            total_passed = sum(r["passed"] for r in test_results)
            total_failed = sum(r["failed"] for r in test_results)
            tracker.complete(bead, output_summary=f"{total_passed} passed, {total_failed} failed",
                           metadata={"passed": total_passed, "failed": total_failed})
            run_record["test_results"] = test_results

            # Commit test files
            await workflow.execute_activity(
                commit_changes, args=[repo_path, f"repo-pilot: add test suite ({run_id})"],
                start_to_close_timeout=timedelta(minutes=1),
            )

            # ━━ Step 8: Push + Merge Request ━━━━━━━━━━━━━━━━━━━━━━━━━
            bead = tracker.create("Push & Create PR", "git",
                                  input_summary=f"Pushing {branch_name}")
            tracker.start(bead)
            await workflow.execute_activity(
                push_branch, args=[repo_path, branch_name],
                start_to_close_timeout=timedelta(minutes=2),
            )

            pr_body = (
                f"## Repo Pilot — Automated Improvements\n\n"
                f"**Run ID:** `{run_id}`\n"
                f"**Improvements Applied:** {applied_count}\n"
                f"**Review Score:** {score}/10\n"
                f"**Tests:** {total_passed} passed, {total_failed} failed\n\n"
                f"### Changes\n" +
                "\n".join(f"- [{c['improvement_id']}] {c['file']}: {c['diff_summary']}"
                          for c in applied_changes if c["status"] == "applied")
            )
            pr_result = await workflow.execute_activity(
                create_merge_request,
                args=[repo_path, branch_name, f"repo-pilot: {applied_count} improvements ({run_id})", pr_body],
                start_to_close_timeout=timedelta(minutes=1),
            )
            tracker.complete(bead, output_summary=pr_result.get("url", "PR created"),
                           metadata=pr_result)
            run_record["merge_result"] = pr_result

            # ━━ Step 8b: Auto-Merge ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            bead = tracker.create("Auto-Merge Decision", "git",
                                  input_summary=f"Score {score} vs threshold {config.AUTO_MERGE_THRESHOLD}")
            tracker.start(bead)
            merge_result = await workflow.execute_activity(
                auto_merge, args=[repo_path, score],
                start_to_close_timeout=timedelta(minutes=1),
            )
            tracker.complete(bead, output_summary=merge_result["status"],
                           metadata=merge_result)
            run_record["merge_result"].update(merge_result)

            # If merged, switch back to main
            if merge_result["status"] == "merged":
                await workflow.execute_activity(
                    checkout_main, args=[repo_path],
                    start_to_close_timeout=timedelta(minutes=1),
                )

            # ━━ Step 9: Update Docs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            bead = tracker.create("Update Documentation", "documentation",
                                  input_summary="Regenerating specification.md, graph.md, architecture.md")
            tracker.start(bead)
            updated_docs = await workflow.execute_activity(
                update_docs, args=[repo_path],
                start_to_close_timeout=timedelta(minutes=5),
            )
            tracker.complete(bead, output_summary=f"Updated {len(updated_docs)} docs")
            run_record["docs_updated"] = updated_docs

            # Commit updated docs
            await workflow.execute_activity(
                commit_changes, args=[repo_path, f"repo-pilot: update docs after improvements ({run_id})"],
                start_to_close_timeout=timedelta(minutes=1),
            )
            # Push updated docs
            if merge_result["status"] == "merged":
                from activities.git_ops import _git
                await workflow.execute_activity(
                    _push_main, args=[repo_path],
                    start_to_close_timeout=timedelta(minutes=1),
                )

            # ━━ Step 10: Final Logging ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            run_record["status"] = "completed"

        except Exception as e:
            log.error("Pipeline failed: %s", e)
            run_record["status"] = "failed"
            run_record["error"] = str(e)

        # Finalize
        total_duration = round(time.monotonic() - pipeline_start, 2)
        run_record["completed_at"] = datetime.now(timezone.utc).isoformat()
        run_record["duration_sec"] = total_duration
        run_record["beads"] = tracker.to_list()
        run_record["bead_summary"] = tracker.summary()

        # Save log file
        bead = tracker.create("Save Pipeline Log", "logging")
        tracker.start(bead)
        log_path = await workflow.execute_activity(
            _save_run_log, args=[run_id, run_record],
            start_to_close_timeout=timedelta(minutes=1),
        )
        tracker.complete(bead, output_summary=log_path)
        run_record["log_file"] = log_path

        log.info("Pipeline %s complete in %.1fs — status: %s",
                 run_id, total_duration, run_record["status"])
        return run_record


# ── Helper activities (registered separately) ─────────────────────────

def _write_analysis_docs(repo_path: str, analysis: dict) -> list[str]:
    """Write the initial analysis docs to the repo."""
    repo = Path(repo_path)
    docs_dir = repo / "docs"
    docs_dir.mkdir(exist_ok=True)
    written = []
    for name, key in [
        ("specification.md", "specification"),
        ("graph.md", "graph"),
        ("architecture.md", "architecture"),
    ]:
        content = analysis.get(key, "")
        if content:
            (docs_dir / name).write_text(content)
            written.append(f"docs/{name}")
    return written


def _push_main(repo_path: str) -> dict:
    """Push main branch to origin."""
    from activities.git_ops import _git
    _git(repo_path, "push", "origin", "main")
    return {"status": "pushed"}


def _save_run_log(run_id: str, run_record: dict) -> str:
    """Save the pipeline run log to the pipeline_runs/ directory."""
    runs_dir = config.PIPELINE_RUNS_DIR
    runs_dir.mkdir(exist_ok=True)
    file_path = runs_dir / f"{run_id}.json"
    with open(file_path, "w") as f:
        json.dump(run_record, f, indent=2, default=str)
    log.info("Run log saved: %s", file_path)
    return str(file_path)
