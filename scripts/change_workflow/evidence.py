"""Evidence: what it describes, and which of it a change's commit still lacks.

Evidence describes a Git tree, or a commit where its result depends on history, as
its kind's pattern keys it with `{tree}` or `{commit}`. A tree is the worktree as
tested (`worktree_tree`): its changes — staged, unstaged, and untracked, but not
what Git ignores — added to a temporary index, never the checkout's own, and
written as a tree. A clean worktree's is `HEAD`'s tree, so evidence gathered before
a commit counts for the commit that then holds exactly what was tested. A commit is
`HEAD`'s full object name, and its evidence is never reused for another commit
sharing its tree.

Evidence counts by being present at its kind's pattern, whoever wrote it: a step, a
hook, the engine, or whatever placed it from beyond the checkout, which the workflow
never fetches from. `evidence <change>` reports, for `HEAD`'s tree and commit, each
kind the configuration declares: required `always`; an owed kind once for each
argument a complete section owes it, or `not required` when none does; `waived`
when the owner's standing decision in the change's log waives it, naming its
`seq`; or an owed line refused, in place of a status. Each names its pattern filled
and every path matching it, in path order, the last current: writers name their
attempts so that path order is time order. A kind not required is listed with
whatever matches and is not assessed.

Contract: openspec/specs/change-workflow/spec.md, CW-t3ev, CW-p4rs, CW-r5qk, CW-e2vd,
and CW-zkhs.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import config, tasks
from .common import Entry, StepError, repository_root
from .config import COMMIT, OWED, TREE, Configuration, Kind
from .find import ChangeNotFound, change_directory
from .log import log_path, read_log, waived_kinds
from .next_step import TASKS_FILE

# What a kind's entry may say of its evidence.
PRESENT, MISSING, WAIVED, NOT_REQUIRED, REFUSED = (
    "present", "missing", "waived", "not required", "refused")


class EvidenceError(StepError):
    """The evidence cannot be read: no commit, or Git failed."""


def _git(root: Path, *arguments: str, environ: Mapping[str, str] | None = None) -> str:
    found = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True,
                           env=None if environ is None else dict(environ))
    if found.returncode != 0:
        raise EvidenceError(f"git {' '.join(arguments)} failed: {found.stderr.strip()}")
    return found.stdout.strip()


def head_commit(root: Path) -> str:
    """`HEAD`'s full object name."""
    return _git(root, "rev-parse", "--verify", "HEAD^{commit}")


def head_tree(root: Path) -> str:
    """The tree `HEAD` holds."""
    return _git(root, "rev-parse", "--verify", "HEAD^{tree}")


def worktree_tree(root: Path) -> str:
    """The tree of the worktree at `root` as it stands: every change to it — staged,
    unstaged, and untracked, but not what Git ignores — added to a copy of the
    checkout's index, which is written as a tree. The checkout's own index is never
    touched, so a step's staging is left as it was."""
    index = root / _git(root, "rev-parse", "--git-path", "index")
    with tempfile.TemporaryDirectory(prefix="change-workflow-tree-") as scratch:
        temporary = Path(scratch) / "index"
        # A copy keeps the index's file states, so Git rereads only what changed. It
        # keeps the index's own modification time too: Git rereads a file changed in
        # the same second as the index was written only by comparing the two, so a
        # copy dated now would pass such a change over as unchanged.
        if index.is_file():
            shutil.copy2(index, temporary)
        environ = {**os.environ, "GIT_INDEX_FILE": str(temporary)}
        _git(root, "add", "--all", environ=environ)
        return _git(root, "write-tree", environ=environ)


def filled(pattern: str, values: Mapping[str, str]) -> str:
    """`pattern` with each placeholder replaced by its value as it is: a path, never
    a shell word, so nothing is quoted."""
    return config.PLACEHOLDER.sub(lambda match: values[match.group(1)], pattern)


def matches(root: Path, pattern: str) -> list[str]:
    """Every path under `root` matching `pattern`, relative to it, in path order."""
    return sorted(glob.glob(pattern, root_dir=root))


@dataclass(frozen=True)
class Required:
    """One entry of the report: a kind, and the argument it is owed for, with the
    sections owing it; what requires it; and the decision waiving it, or the
    refusal of the owed line naming it."""

    kind: str | None
    requirement: str
    owed: str | None = None
    sections: tuple[str, ...] = ()
    waiver: Entry | None = None
    refusal: str | None = None


def requirements(configuration: Configuration, owed: Sequence[tasks.Owed],
                 waived: Mapping[str, Entry]) -> list[Required]:
    """Each kind's entries, in declaration order: an `always` kind once; an owed kind
    once per argument the complete sections owe it, in the order they first owe it,
    each refused line naming it after them, or once `not required`. A refused line
    naming no owed kind follows every kind."""
    config.require(configuration, config.EVIDENCE, needed_by="the evidence report")
    found: list[Required] = []
    owed_names = set(tasks.owed_kinds(configuration))
    for kind in configuration.kinds or ():
        waiver = waived.get(kind.name)
        if not kind.owed:
            found.append(Required(kind.name, config.ALWAYS, waiver=waiver))
            continue
        arguments: dict[str, list[str]] = {}
        for line in owed:
            if line.kind == kind.name and line.refusal is None and line.argument:
                sections = arguments.setdefault(line.argument, [])
                if line.section not in sections:
                    sections.append(line.section)
        found += [Required(kind.name, OWED, argument, tuple(sections), waiver)
                  for argument, sections in arguments.items()]
        refused = [line for line in owed if line.refusal and line.kind == kind.name]
        found += [Required(kind.name, OWED, sections=(line.section,), refusal=line.refusal)
                  for line in refused]
        if not arguments and not refused:
            found.append(Required(kind.name, NOT_REQUIRED, waiver=waiver))
    found += [Required(line.kind, OWED, sections=(line.section,), refusal=line.refusal)
              for line in owed if line.refusal and line.kind not in owed_names]
    return found


@dataclass(frozen=True)
class Report:
    """The evidence report: the identities it was read for, and each entry."""

    tree: str
    commit: str
    entries: list[dict[str, Any]] = field(default_factory=list)


def report(root: Path, configuration: Configuration, owed: Sequence[tasks.Owed],
           waived: Mapping[str, Entry], tree: str, commit: str) -> Report:
    """The report for `tree` and `commit`: each entry its pattern filled, the paths
    matching it, the last current, and its status."""
    kinds = {kind.name: kind for kind in configuration.kinds or ()}
    entries = []
    for required in requirements(configuration, owed, waived):
        kind: Kind | None = kinds.get(required.kind) if required.refusal is None else None
        entry: dict[str, Any] = {"kind": required.kind, "owed": required.owed,
                                 "sections": list(required.sections),
                                 "requirement": required.requirement}
        if kind is not None:
            # A kind not required is matched for whatever any argument left.
            values = {TREE: tree, COMMIT: commit, OWED: required.owed or "*"}
            pattern = filled(kind.evidence, values)
            found = matches(root, pattern)
            entry.update(identity=kind.identity, pattern=pattern, matches=found,
                         current=found[-1] if found else None)
        if required.refusal is not None:
            entry.update(status=REFUSED, refusal=required.refusal)
        elif required.waiver is not None:
            entry.update(status=WAIVED, waived={"seq": required.waiver["seq"],
                                                "decision": required.waiver["decision"]})
        elif required.requirement == NOT_REQUIRED:
            entry["status"] = NOT_REQUIRED
        else:
            entry["status"] = PRESENT if entry["matches"] else MISSING
        entries.append(entry)
    return Report(tree, commit, entries)


def change_report(root: Path, change: str, configuration: Configuration | None = None
                  ) -> Report:
    """The report for `change` at `HEAD`, its owed lines read from its task list and
    its waivers from its log."""
    configuration = config.load(root) if configuration is None else configuration
    try:
        directory = change_directory(root, change)
    except ChangeNotFound as exc:
        raise EvidenceError(str(exc)) from exc
    owed = tasks.owed_lines(directory / TASKS_FILE, tasks.owed_kinds(configuration))
    log = log_path(root, change)
    waived = waived_kinds(read_log(log)) if log.exists() else {}
    return report(root, configuration, owed, waived, head_tree(root), head_commit(root))


def label(entry: Mapping[str, Any]) -> str:
    """How the report names an entry: its kind, and the argument it is owed for; a
    refused owed line naming no kind, as an owed line."""
    return " ".join(part for part in (entry["kind"], entry.get("owed")) if part) or "owed line"


def lines(shown: Report) -> list[str]:
    """The report as lines for reading."""
    found = [f"{'tree':<8} {shown.tree}", f"{'commit':<8} {shown.commit}"]
    for entry in shown.entries:
        status = entry["status"]
        owing = (f"owed by section{'s' if len(entry['sections']) > 1 else ''} "
                 + ", ".join(entry["sections"])) if entry["owed"] else ""
        found.append("   ".join(text for text in (
            f"{label(entry):<20} {status:<12}", entry.get("pattern", ""), owing) if text))
        if status == REFUSED:
            found.append(f"    {entry['refusal']}")
        if status == WAIVED:
            found.append(f"    waived by the owner at seq {entry['waived']['seq']}: "
                         f"{entry['waived']['decision']}")
        for path in entry.get("matches", []):
            found.append(f"    {path}" + ("   current" if path == entry["current"] else ""))
    return found


def as_json(shown: Report) -> str:
    return json.dumps({"tree": shown.tree, "commit": shown.commit, "kinds": shown.entries},
                      ensure_ascii=False)


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """`evidence <change> [--json]`: the change's evidence at `HEAD`, 0 however much
    of it is missing, 1 when it cannot be read."""
    parser = argparse.ArgumentParser(prog="change-workflow evidence")
    parser.add_argument("change")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = repository_root() if root is None else root
        shown = change_report(root, args.change)
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(as_json(shown) if args.json else "\n".join(lines(shown)))
    return 0
