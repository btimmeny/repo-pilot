"""
Backward-compatibility shim — beads feature has moved to features.beads.

All imports from this package are re-exported from the new location.
"""

from features.beads.models import Bead, BeadStatus  # noqa: F401
from features.beads.tracker import BeadTracker  # noqa: F401
