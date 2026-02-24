"""
Configuration — loads settings from environment / .env file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).parent
TARGET_REPO_PATH = Path(os.getenv("TARGET_REPO_PATH", ""))
PIPELINE_RUNS_DIR = PROJECT_ROOT / "pipeline_runs"

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")

# Temporal
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_TASK_QUEUE = "repo-pilot-queue"
TEMPORAL_NAMESPACE = "default"

# Pipeline
AUTO_MERGE_THRESHOLD = float(os.getenv("AUTO_MERGE_THRESHOLD", "7.0"))
IMPROVEMENT_BRANCH_PREFIX = "repo-pilot"

# File extensions to analyze
ANALYZABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".md", ".yml", ".yaml",
    ".json", ".toml", ".cfg", ".ini", ".txt", ".sh", ".html", ".css",
}

# Max file size to send to LLM (characters)
MAX_FILE_SIZE = 8_000

# Max total context characters to send in a single LLM call (~4 chars per token)
MAX_CONTEXT_CHARS = 60_000
