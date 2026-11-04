#!/usr/bin/env python3
"""Entry point of the engine's change lookup, `change_workflow.find`.

Callers run this path by its location to act on the checkout it sits in, from any
directory — the orchestrating session runs a clone's copy from the workspace — and
the engine acts on its working directory's repository, so the working directory
is this checkout's before the engine runs.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_workflow.find import main  # noqa: E402

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    sys.exit(main())
