#!/usr/bin/env python3
"""Entry point of the engine's post-compaction hook, `change_workflow.hook`.

The hook runs this path from the project directory Claude Code names, and the
engine acts on its working directory's repository, so the working directory is
this checkout's before the engine runs, whatever directory the session is in.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_workflow.hook import main  # noqa: E402

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    sys.exit(main())
