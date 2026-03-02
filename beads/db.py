"""
Backward-compatibility shim — beads.db has moved to features.beads.db.

All symbols are re-exported from the new location.
"""

from features.beads.db import (  # noqa: F401
    init_db,
    upsert_pipeline_run,
    get_pipeline_run,
    list_pipeline_runs,
    upsert_bead,
    get_beads_for_run,
    get_bead,
    get_beads_by_status,
    get_beads_by_category,
    get_bead_summary,
    get_cursor,
    SCHEMA_SQL,
)
