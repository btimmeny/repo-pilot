"""
Temporal Worker — registers the workflow and activities, then polls for tasks.

Usage:
    python worker.py
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

import config
from workflows.pipeline import (
    CodeImprovementPipeline,
    _write_analysis_docs,
    _push_main,
    _save_run_log,
)
from activities.analyze import analyze_repo
from activities.suggest import suggest_improvements
from activities.execute_changes import execute_changes
from activities.review import review_changes
from activities.test_gen import generate_tests
from activities.test_run import run_tests
from activities.git_ops import (
    create_branch,
    commit_changes,
    push_branch,
    create_merge_request,
    auto_merge,
    checkout_main,
)
from activities.update_docs import update_docs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ALL_ACTIVITIES = [
    analyze_repo,
    suggest_improvements,
    execute_changes,
    review_changes,
    generate_tests,
    run_tests,
    create_branch,
    commit_changes,
    push_branch,
    create_merge_request,
    auto_merge,
    checkout_main,
    update_docs,
    _write_analysis_docs,
    _push_main,
    _save_run_log,
]


async def main():
    log.info("Connecting to Temporal at %s", config.TEMPORAL_HOST)
    client = await Client.connect(config.TEMPORAL_HOST)

    log.info("Starting worker on queue: %s", config.TEMPORAL_TASK_QUEUE)
    worker = Worker(
        client,
        task_queue=config.TEMPORAL_TASK_QUEUE,
        workflows=[CodeImprovementPipeline],
        activities=ALL_ACTIVITIES,
    )

    log.info("Worker ready — listening for tasks")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
