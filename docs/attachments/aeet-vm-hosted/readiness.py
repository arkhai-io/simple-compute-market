"""Gate hosted VM qualification before pytest; configured targets must be ready."""

from pathlib import Path
import runpy

# The shared gate checks host-authority health and an authenticated publication,
# reading the current settlement envelope rather than the retired mechanism key.
runpy.run_path(str(Path(__file__).parents[1] / "vm-end-classification" / "readiness.py"))
