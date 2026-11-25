"""The specification index check, `change-workflow check spec-index [<change>]`: an
indexed capability's `spec.md` held to its `index.md`.

A capability under `openspec/specs/` may organize its documentation by an index
(the workflow guidance's section "A capability organized by an index"). Its
`index.md` declares the capability's id prefix on a line `Prefix: `CW``; lists each
requirement by id, as a list item or table row whose first cell is a link
`[CW-a8tf](spec.md#…)` followed by its summary line, under the parts and groups of
its table of contents; and lists the ids it retired under `## Retired ids`, each item
beginning with the id. Every requirement in its `spec.md` is named `### Requirement:
<ID> <name>`, the id the prefix, a hyphen, and four characters from `[a-z0-9]`.

The check fails, naming each, on: a requirement whose name begins with no such id;
two requirements sharing an id; an id `index.md` omits or lists twice; a listed id
in neither `spec.md` nor the named change's deltas; a retired id in use; a link in
`index.md` whose file or heading does not resolve; and an entry whose link is not to
its own id's requirement heading in `spec.md`. A capability with no `index.md` is
not checked.

Closeout writes `index.md` before the archive merges the change's deltas into
`spec.md`, so with an active change named its deltas count as the archive will leave
them: an id its deltas add or rename to is in the specification, its headings
resolve, and a requirement its deltas remove or rename from is gone. A capability the
change creates has no `spec.md` before the archive; when its deltas add a requirement,
its links to `spec.md` resolve against the deltas alone. An archived change's deltas
are merged already, so none is counted.

It is one of `pre-commit`'s default checks, run with the change named. With
`--json` it prints, beside the result and each problem, the specification paths the
change's deltas create (`created`), so a repository's own checks learn them without
reading the deltas: a capability's `spec.md` that does not exist and that a delta
adding a requirement will write, the one operation that can create it.

Contract: openspec/specs/change-workflow/spec.md, CW-c8lw and CW-368t.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .common import StepError, repository_root
from .find import ChangeNotFound, change_directory, is_archived

SPECS = Path("openspec/specs")
INDEX = "index.md"
SPEC = "spec.md"

_PREFIX = re.compile(r"^Prefix:\s*`(?P<prefix>[A-Z]+)`\s*$", re.M)
_REQUIREMENT = re.compile(r"^###\s+Requirement:\s*(?P<name>.+?)\s*$", re.M)
_HEADING = re.compile(r"^#{1,6}\s+(?P<text>.+?)\s*#*\s*$")
_DELTA_SECTION = re.compile(r"^##\s+(?P<operation>ADDED|MODIFIED|REMOVED|RENAMED)\s+"
                            r"Requirements\s*$")
_RENAMED = re.compile(r"^\s*-\s*(?P<side>FROM|TO):\s*`?###\s+Requirement:\s*(?P<name>.+?)`?\s*$")
_LINK = re.compile(r"(?<!!)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")
_RETIRED = re.compile(r"^##\s+Retired ids\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _id_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"^(?P<id>{re.escape(prefix)}-[a-z0-9]{{4}})(?=\s|$)")


def slug(heading: str) -> str:
    """A heading's anchor as GitHub writes it: lower case, punctuation dropped,
    spaces as hyphens."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _outside_fences(text: str) -> list[str]:
    lines, fenced = [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        lines.append("" if fenced else line)
    return lines


def anchors(text: str) -> set[str]:
    return {slug(match["text"]) for line in _outside_fences(text)
            if (match := _HEADING.match(line))}


@dataclass
class Deltas:
    """What a change's delta for one capability leaves once archived: the
    requirement names it adds, modifies, or renames to, and those it removes or
    renames from. `added` holds only the names it adds, the one operation that can
    create a capability's `spec.md`: a modification or rename needs a requirement
    already there."""

    present: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)


def read_deltas(text: str) -> Deltas:
    deltas = Deltas()
    operation = None
    for line in _outside_fences(text):
        if section := _DELTA_SECTION.match(line):
            operation = section["operation"]
        elif line.startswith("## "):
            operation = None
        elif operation == "RENAMED" and (renamed := _RENAMED.match(line)):
            (deltas.present if renamed["side"] == "TO" else deltas.removed).append(
                renamed["name"])
        elif operation in ("ADDED", "MODIFIED", "REMOVED") and (
                requirement := _REQUIREMENT.match(line)):
            (deltas.removed if operation == "REMOVED" else deltas.present).append(
                requirement["name"])
            if operation == "ADDED":
                deltas.added.append(requirement["name"])
    return deltas


@dataclass(frozen=True)
class Entry:
    """One listed id, the line it is on, and where its link points."""

    line: int
    id: str
    target: str


@dataclass(frozen=True)
class Index:
    prefix: str | None
    entries: list[Entry]
    retired: list[str]
    links: list[tuple[int, str]]

    @property
    def listed(self) -> list[str]:
        return [entry.id for entry in self.entries]


def read_index(text: str) -> Index:
    """The prefix `index.md` declares, the ids it lists with their links and the ids
    it retires, and each link with its line number. A retired id may be written
    bare, in backticks, or as the link its entry carried before it was retired."""
    prefix = match["prefix"] if (match := _PREFIX.search("\n".join(_outside_fences(text)))) \
        else None
    entry = re.compile(r"^\s*(?:[-*+]|\|)\s*\[(?P<id>[A-Z]+-[a-z0-9]{4})\]"
                       r"\((?P<target>[^)\s]*)")
    retiring = re.compile(r"^\s*(?:[-*+]|\|)\s*[`\[]?(?P<id>[A-Z]+-[a-z0-9]{4})\b")
    entries: list[Entry] = []
    retired: list[str] = []
    links: list[tuple[int, str]] = []
    in_retired = False
    for number, line in enumerate(_outside_fences(text), start=1):
        if line.startswith("## "):
            in_retired = bool(_RETIRED.match(line))
        links += [(number, link["target"]) for link in _LINK.finditer(line)]
        if in_retired and (found := retiring.match(line)):
            retired.append(found["id"])
        elif not in_retired and (found := entry.match(line)):
            entries.append(Entry(number, found["id"], found["target"]))
    return Index(prefix, entries, retired, links)


def _duplicates(values: Sequence[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _link_problem(capability: Path, target: str, deltas: Deltas) -> str | None:
    """Why a link in `index.md` does not resolve; None when it does. A URL, a link
    with a scheme, is not followed. A heading of `spec.md` is read as the deltas
    will leave it: the headings they add or rename to resolve, and those they
    remove or rename from do not, whether or not `spec.md` exists yet."""
    if re.match(r"^[a-z][a-z0-9+.-]*:", target):
        return None
    path, _, fragment = target.partition("#")
    file = (capability / path).resolve() if path else capability / INDEX
    is_spec = file == (capability / SPEC).resolve()
    # A capability new with the change has no spec.md until the archive writes it
    # from the requirements the deltas add, so its links resolve against the deltas;
    # deltas that add none cannot write it, and it stays missing.
    if not file.exists() and not (is_spec and deltas.added):
        return f"its file {path} does not exist"
    if not fragment or file.is_dir():
        return None
    known = anchors(file.read_text("utf-8")) if file.suffix == ".md" and file.exists() \
        else set()
    if is_spec:
        known = (known - {_requirement_anchor(name) for name in deltas.removed}) | {
            _requirement_anchor(name) for name in deltas.present}
    return None if fragment in known else f"{file.name} has no heading #{fragment}"


def _requirement_anchor(name: str) -> str:
    return slug(f"Requirement: {name}")


def _links_to(capability: Path, target: str, anchor: str) -> bool:
    """Whether an entry's link is to `anchor` in the capability's `spec.md`."""
    path, _, fragment = target.partition("#")
    return bool(path) and (capability / path).resolve() == (capability / SPEC).resolve() \
        and fragment == anchor


def capability_problems(capability: Path, deltas: Deltas | None = None) -> list[str]:
    """Each way `capability`'s `spec.md` and `index.md` disagree; empty when they
    agree, or when it has no `index.md`."""
    index_file = capability / INDEX
    if not index_file.is_file():
        return []
    name = capability.name
    index = read_index(index_file.read_text("utf-8"))
    if index.prefix is None:
        return [f"{name}: {INDEX} declares no prefix on a line `Prefix: `<PREFIX>``"]
    deltas = deltas or Deltas()
    pattern = _id_pattern(index.prefix)
    spec_file = capability / SPEC
    spec_text = spec_file.read_text("utf-8") if spec_file.is_file() else ""
    removed = set(deltas.removed)
    names = [match["name"] for match in _REQUIREMENT.finditer("\n".join(_outside_fences(
        spec_text))) if match["name"] not in removed]
    # A requirement renamed and modified is named by both blocks: one requirement.
    added = [requirement for requirement in dict.fromkeys(deltas.present)
             if requirement not in names]
    problems = []
    ids = []
    requirement_of: dict[str, str] = {}
    for requirement in [*names, *added]:
        if found := pattern.match(requirement):
            ids.append(found["id"])
            requirement_of.setdefault(found["id"], requirement)
        else:
            problems.append(f"{name}: requirement {requirement!r} begins with no id "
                            f"({index.prefix}- and four characters from [a-z0-9])")
    problems += [f"{name}: two requirements share the id {shared}" for shared in
                 _duplicates(ids)]
    problems += [f"{name}: {INDEX} does not list {missing}"
                 for missing in sorted(set(ids) - set(index.listed))]
    problems += [f"{name}: {INDEX} lists {twice} twice" for twice in
                 _duplicates(index.listed)]
    problems += [f"{name}: {INDEX} lists {unknown}, which neither {SPEC} nor the change's "
                 "deltas hold"
                 for unknown in sorted(set(index.listed) - set(ids))]
    problems += [f"{name}: the retired id {reused} is in use"
                 for reused in sorted(set(index.retired) & (set(ids) | set(index.listed)))]
    problems += [f"{name}: {INDEX}:{line}: the link {target} does not resolve: {why}"
                 for line, target in index.links
                 if (why := _link_problem(capability, target, deltas))]
    # A link that resolves may still reach another requirement's heading, so each
    # entry is held to the heading of the requirement its own id names.
    shared = set(_duplicates(ids))
    for entry in index.entries:
        if entry.id not in requirement_of or entry.id in shared:
            continue
        anchor = _requirement_anchor(requirement_of[entry.id])
        if not _links_to(capability, entry.target, anchor):
            problems.append(f"{name}: {INDEX}:{entry.line}: {entry.id} links to "
                            f"{entry.target}, not to its requirement's heading "
                            f"{SPEC}#{anchor}")
    return problems


def change_deltas(root: Path, change: str | None) -> dict[str, Deltas]:
    """Each capability's deltas in the named change, by capability; none without a
    change, or for an archived one, whose deltas the archive has merged."""
    if change is None:
        return {}
    directory = change_directory(root, change)
    if is_archived(root, directory):
        return {}
    return {delta.parent.name: read_deltas(delta.read_text("utf-8"))
            for delta in sorted(directory.glob(f"specs/*/{SPEC}"))}


def problems(root: Path, deltas: dict[str, Deltas] | None = None) -> list[str]:
    """Every indexed capability's problems, the change's `deltas` counted."""
    specs = root / SPECS
    deltas = deltas or {}
    found = []
    for capability in sorted(path for path in specs.iterdir() if path.is_dir()) \
            if specs.is_dir() else []:
        found += capability_problems(capability, deltas.get(capability.name))
    return found


def created(root: Path, deltas: dict[str, Deltas]) -> list[str]:
    """The specification paths `deltas` create, as the repository cites them: each
    capability's `spec.md` that does not exist, where its delta adds a requirement."""
    return [(SPECS / name / SPEC).as_posix() for name, delta in sorted(deltas.items())
            if delta.added and not (root / SPECS / name / SPEC).is_file()]


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """`check spec-index [<change>] [--json]`: 0 when every indexed capability agrees
    with its index, 1 when one does not or the change is not found."""
    parser = argparse.ArgumentParser(prog="change-workflow check spec-index")
    parser.add_argument("change", nargs="?", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    change = args.change or None
    try:
        root = repository_root() if root is None else root
        deltas = change_deltas(root, change)
    except (ChangeNotFound, StepError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    found = problems(root, deltas)
    if args.json:
        print(json.dumps({"change": change, "result": "failed" if found else "passed",
                          "problems": found, "created": created(root, deltas)},
                         ensure_ascii=False))
        return 1 if found else 0
    for problem in found:
        print(f"FAIL: {problem}")
    if found:
        return 1
    print("OK: every indexed capability's spec.md agrees with its index.md")
    return 0
