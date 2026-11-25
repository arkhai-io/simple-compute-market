"""A stand-in for the installed change workflow's command, for the suites of this
repository's scripts that reach the workflow, since those suites run without it
installed.

It is put first on the path as `change-workflow`, where `workflow_command` finds the
command, and answers with what the test gives it, in the structured output those
scripts read:

- `find --json <change>`: the object the test gives for that name; for any other
  name, a refusal naming it on standard error, as the workflow refuses;
- `check spec-index <change> --json`, for a name the test gives: the specification
  paths the test says the change's deltas create, in `created`.

It decides nothing itself: which change a name finds, and what a delta creates, are
the workflow's to compute and to test.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

import pytest

SCRIPT = '''
import json, sys
from pathlib import Path

answers = json.loads(Path(sys.argv[0]).with_name("answers.json").read_text("utf-8"))
arguments = sys.argv[1:]


def found(name):
    if name not in answers["found"]:
        sys.exit(f"ERROR: no change {name!r}")
    return answers["found"][name]


if arguments[:2] == ["find", "--json"] and len(arguments) == 3:
    print(json.dumps(found(arguments[2])))
elif arguments[:2] == ["check", "spec-index"] and arguments[3:] == ["--json"]:
    found(arguments[2])
    print(json.dumps({"result": "passed", "created": answers["created"]}))
else:
    sys.exit(f"ERROR: the stand-in answers no {' '.join(arguments)!r}")
'''


def change(name: str, directory: str, *, archived: bool = False,
           records: str | None = None) -> dict[str, dict[str, object]]:
    """The answer `find --json` gives for `name`: its directory relative to the
    checkout, whether it is archived, and its records directory, or None."""
    return {name: {"name": name, "directory": directory, "archived": archived,
                   "records": records, "format": 2, "base": None}}


def put_on_path(monkeypatch: pytest.MonkeyPatch, directory: Path,
                found: Mapping[str, Mapping[str, object]] | None = None,
                created: Iterable[str] = ()) -> Path:
    """Writes the stand-in into `directory`, answering `find --json` with `found`, by
    change name, and reporting `created` as what a found change's deltas create, and
    puts it first on the path; the stand-in's path."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "answers.json").write_text(
        json.dumps({"found": dict(found or {}), "created": sorted(created)}), "utf-8")
    command = directory / "change-workflow"
    command.write_text(f"#!{sys.executable} -I\n{SCRIPT}", "utf-8")
    command.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    return command
