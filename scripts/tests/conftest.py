"""The scripts' tests import the scripts' own modules and packages by name, as the
scripts themselves do, so `scripts/` is on the path before any test is collected."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
