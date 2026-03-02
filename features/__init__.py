"""
Features package — each sub-package encapsulates a self-contained feature.

Convention:
  features/<feature_name>/
    __init__.py      — public API re-exports
    models.py        — data models specific to this feature
    db.py            — database layer (if applicable)
    tracker.py       — runtime tracking / state management (if applicable)
    ...              — any other feature-specific modules
"""
