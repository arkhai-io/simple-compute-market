#!/usr/bin/env python3
"""Run a step of an OpenSpec change unattended, and keep the change's workflow log.

An entry point of the engine's command, `change_workflow.cli`, under the name the
`Makefile`'s workflow targets, the step table's rules, and the skills run: each of
its commands — `resume`, `review`, `record`, `convert`, `log`, `note`, `watch`, and
`denials` — is the command's subcommand of the same name, and `run <step>
<change>` is `start <step> <change> --unattended`.

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


def command(argv: list[str]) -> list[str]:
    """The command's arguments for this script's: `run` is an unattended `start`."""
    return ["start", *argv[1:], "--unattended"] if argv[:1] == ["run"] else argv


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    sys.exit(main(command(sys.argv[1:])))
