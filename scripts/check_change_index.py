#!/usr/bin/env python3
"""Check the active-change index against the change directories it describes.

`openspec/changes/README.md` is read by every workflow step to decide what may
start next, and the steps that edit it — triage at a phase-closing gate,
closeout, archive cleanup — change rows by hand. The citation check does not
read it: its links are relative directory links, not cited paths. This check
holds what a hand edit can break:

- every table row has as many cells as its table's header;
- every row's change link resolves to that change's directory; an `archived`
  row links its archive, and a row linking an archive is `archived`, or
  `in closeout` between closeout's archive and archive cleanup;
- every status is one of the legend's values;
- every `Depends on` entry names a change the index lists and that is not
  `archived`, with a phase, if any, from the phase list;
- every change directory under `openspec/changes/` has a row.

The dependency graphs are illustrations and are not checked: the legend makes
the `Depends on` column authoritative.

Run as a script, it prints each problem with its line and exits non-zero, or
prints OK.

Contract: openspec/specs/planning-governance/spec.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]
CHANGES = Path("openspec/changes")
INDEX = CHANGES / "README.md"

PHASES = ("design", "planning", "implementation", "closeout")
STATUSES = frozenset(
    [f"{state} {phase}" for state in ("ready for", "in", "blocked in") for phase in PHASES]
    + ["deferred", "archived"]
)
_LINK = re.compile(r"\[`(?P<name>[^`]+)`\]\((?P<path>[^)]*)\)")
_DEPENDENCY = re.compile(r"^`(?P<name>[a-z0-9-]+)`(?: \((?P<phase>[a-z]+)\))?$")
_ARCHIVED = re.compile(r"^archive/\d{4}-\d{2}-\d{2}-(?P<name>.+)/$")


class Row(NamedTuple):
    line: int
    name: str
    path: str
    status: str
    depends_on: str | None


def _cells(line: str) -> list[str]:
    # A `|` escaped inside a cell is not a column boundary.
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]


def _rows(lines: Sequence[str]) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    problems: list[str] = []
    header: list[str] | None = None
    for number, line in enumerate(lines, 1):
        if not line.startswith("|"):
            header = None
            continue
        if line.startswith("|---"):
            continue
        if number < len(lines) and lines[number].startswith("|---"):
            header = _cells(line)
            continue
        if header is None:
            problems.append(f"{INDEX}:{number}: a table row with no header")
            continue
        cells = _cells(line)
        if len(cells) != len(header):
            problems.append(
                f"{INDEX}:{number}: {len(cells)} cells under a header of {len(header)}")
            continue
        if "Change" not in header or "Status" not in header:
            continue
        row = dict(zip(header, cells))
        link = _LINK.search(row["Change"])
        if link is None:
            problems.append(f"{INDEX}:{number}: the Change cell links no change")
            continue
        rows.append(Row(number, link.group("name"), link.group("path"), row["Status"],
                        row.get("Depends on")))
    return rows, problems


def _check_row(root: Path, row: Row) -> list[str]:
    where = f"{INDEX}:{row.line}: {row.name}"
    problems = []
    if row.status not in STATUSES:
        problems.append(f"{where}: status {row.status!r} is not in the legend")
    archived = _ARCHIVED.match(row.path)
    if archived is None and row.path != f"{row.name}/":
        problems.append(f"{where}: links {row.path!r}, not its own directory")
    elif archived is not None and archived.group("name") != row.name:
        problems.append(f"{where}: links {row.path!r}, another change's archive")
    elif not (root / CHANGES / row.path).is_dir():
        problems.append(f"{where}: links {row.path!r}, which does not exist")
    if row.status == "archived" and archived is None:
        problems.append(f"{where}: archived but links {row.path!r}, not its archive")
    elif archived is not None and row.status not in ("archived", "in closeout"):
        problems.append(
            f"{where}: links its archive but is {row.status!r}; only an archived change, "
            "or one in closeout after its archive, does")
    return problems


def _check_dependencies(rows: Sequence[Row]) -> list[str]:
    status = {row.name: row.status for row in rows}
    problems = []
    for row in rows:
        if row.depends_on in (None, "—"):
            continue
        for entry in (part.strip() for part in row.depends_on.split(",")):
            where = f"{INDEX}:{row.line}: {row.name} depends on {entry}"
            match = _DEPENDENCY.match(entry)
            if match is None:
                problems.append(f"{where}: not a change name with an optional (phase)")
            elif match.group("phase") is not None and match.group("phase") not in PHASES:
                problems.append(f"{where}: {match.group('phase')!r} is not a phase")
            elif match.group("name") not in status:
                problems.append(f"{where}: the index lists no such change")
            elif status[match.group("name")] == "archived":
                problems.append(
                    f"{where}: that change is archived, so archive cleanup releases it")
    return problems


def check(root: Path = ROOT) -> list[str]:
    """Every problem in the index, each naming its line."""
    lines = (root / INDEX).read_text("utf-8").splitlines()
    rows, problems = _rows(lines)
    for row in rows:
        problems.extend(_check_row(root, row))
    problems.extend(_check_dependencies(rows))
    listed = {row.name for row in rows}
    changes = root / CHANGES
    for directory in sorted(p for p in changes.iterdir() if p.is_dir()):
        if directory.name != "archive" and directory.name not in listed:
            problems.append(f"{INDEX}: no row for {directory.relative_to(root).as_posix()}/")
    return problems


def main(root: Path = ROOT) -> int:
    problems = check(root)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"OK: {INDEX} matches the change directories it lists.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
