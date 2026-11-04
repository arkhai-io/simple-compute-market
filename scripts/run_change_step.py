#!/usr/bin/env python3
"""Run a step of an OpenSpec change unattended, and keep the change's workflow log.

The entry point of the `change_workflow` package beside this script, whose `cli`
dispatches each command — `run`, `resume`, `review`, `record`, `convert`, `log`,
`note`, `watch`, and `denials` — to the module that does its work. The `Makefile`'s workflow targets,
the step table's rules, and the skills name this script, so it stays where they
look.

Callers run this path by its location to act on the checkout it sits in, from any
directory — the orchestrating session runs a clone's copy from the workspace — and
the engine acts on its working directory's repository, so the working directory
is this checkout's before the engine runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_workflow.cli import main  # noqa: E402

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    sys.exit(main())
