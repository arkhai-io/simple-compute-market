#!/usr/bin/env python3
"""Fail if a decision a change's design records names no permanent destination.

Every accepted decision is promoted to a permanent document before the change is
complete, so the proposal's "Knowledge to promote" names where each one goes
(`openspec/README.md`, "Change documentation requirements"). A design records its
decisions under `### D<n>` headings in its `## Decisions` section; each must have
a bullet in "Knowledge to promote" starting `D<n>`, which names the destination
or says `D<n>: no permanent destination — <reason>`. A design with no such
heading passes, reported as not checked: it records its decisions some other
way, and this check cannot read them. Headings inside fenced code blocks are
examples, not decisions.

Run by `make check-repository`, the change workflow's `pre-commit`. Usage: `check_decision_destinations.py <change>`.

Contract: openspec/specs/market-change-workflow/spec.md, MCW-c4ek.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workflow_command import WorkflowRefused, found_change  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DESIGN_FILE = "design.md"
PROPOSAL_FILE = "proposal.md"
_DECISION = re.compile(r"^### (D\d+)\b")
_BULLET = re.compile(r"^\s*[-*]\s+(D\d+)\b")
_HEADING = re.compile(r"^(#+)\s")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CLOSING = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")


def _prose(text: str) -> list[str]:
    """The lines of a Markdown document outside fenced code blocks. As in
    CommonMark, a fence closes only on a bare run of its own character at least
    as long as its opening, so a line opening another fence inside it does not."""
    lines: list[str] = []
    opening: str | None = None
    for line in text.splitlines():
        if opening is None and (fence := _FENCE.match(line)):
            opening = fence.group(1)
        elif opening is not None:
            closing = _CLOSING.match(line)
            if (closing and closing.group(1)[0] == opening[0]
                    and len(closing.group(1)) >= len(opening)):
                opening = None
        else:
            lines.append(line)
    return lines


def _section(lines: list[str], title: str, level: int | None = None) -> list[str] | None:
    """The lines under the heading whose text is `title`, of `level` when named,
    up to the next heading of its level or above, or None when there is none."""
    for index, line in enumerate(lines):
        heading = _HEADING.match(line)
        if (heading and line[heading.end():].strip() == title
                and level in (None, len(heading.group(1)))):
            level = len(heading.group(1))
            body = []
            for following in lines[index + 1:]:
                found = _HEADING.match(following)
                if found and len(found.group(1)) <= level:
                    break
                body.append(following)
            return body
    return None


def decisions(design: str) -> list[str]:
    """The `D<n>` of each `### D<n>` heading in a design's `## Decisions`."""
    section = _section(_prose(design), "Decisions", level=2) or []
    return [match.group(1) for line in section if (match := _DECISION.match(line))]


def promoted(proposal: str) -> set[str]:
    """The `D<n>` each bullet of a proposal's "Knowledge to promote" starts with."""
    section = _section(_prose(proposal), "Knowledge to promote") or []
    return {match.group(1) for line in section if (match := _BULLET.match(line))}


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1 or not args[0]:
        print("usage: check_decision_destinations.py <change>", file=sys.stderr)
        return 2
    try:
        directory = root / str(found_change(root, args[0])["directory"])
    except WorkflowRefused as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    design, proposal = directory / DESIGN_FILE, directory / PROPOSAL_FILE
    recorded = decisions(design.read_text("utf-8")) if design.is_file() else []
    if not recorded:
        print(f"OK: not checked; {args[0]}'s design records no `### D<n>` decision heading "
              "under `## Decisions`.")
        return 0
    named = promoted(proposal.read_text("utf-8")) if proposal.is_file() else set()
    if missing := [decision for decision in recorded if decision not in named]:
        shown = proposal.relative_to(root).as_posix()
        for decision in missing:
            print(f"{shown}: {decision} has no bullet starting `{decision}` in "
                  "\"Knowledge to promote\"")
        print()
        print("FAIL: name each decision's permanent destination in \"Knowledge to promote\",")
        print("or say `- D<n>: no permanent destination — <reason>`.")
        return 1
    print(f"OK: each of {args[0]}'s {len(recorded)} decisions names its destination.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
