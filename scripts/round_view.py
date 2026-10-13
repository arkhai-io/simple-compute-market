#!/usr/bin/env python3
"""Show an implementation round as uncommitted changes in the checkout itself.

Implementation commits each section, so by the time the owner reads a round its
diff is spread across commits and the editor's source-control view is empty.
`start` moves the branch back to the round's base with a mixed reset: the files
stay exactly HEAD's, and the round shows as uncommitted changes the owner reads,
and runs tests against, in place. `done` resets the branch to the recorded HEAD;
the files again stay as they are, so any edit the owner made while reading is
left as an uncommitted change on top of the round's commit. Staging done during
the view is not kept; the content is.

A commit made during the view — an editor's "commit all" is easy to click —
lands on the base and squashes the round into itself. `done` still returns: the
worktree holds what such a commit captured, unless it was changed again since,
so the branch is reset to the round's commit, that commit's own changes are left
uncommitted on top, and the commits taken off the branch are named so nothing
else depends on the reflog. A view whose branch is already at the round's commit,
or past it — left by hand, a run interrupted before its reset, a fix committed
after returning — is closed without moving the branch.

The base is the commit named by the latest triaged validation record — where
the previous round ended — unless one is given.

While a view is open the branch does not point at the round's commit, so every
step that describes a commit — review, validation, triage, implementation —
refuses (`check`). `start` can first push HEAD and dispatch the end-to-end
pipeline, so the slowest part of validation overlaps the owner's reading; it
records the newest earlier run, which validation reads once, and forgets, to
fetch that run.

The state lives in the Git directory of this worktree, so a view and its baseline
belong to the checkout that opened them.

Contract: openspec/specs/change-workflow/spec.md, "Triage of an implementation
round".
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
CHANGES = "openspec/changes"
STATE = "round-view.json"
E2E_BASELINES = "round-view-e2e"
_NUMBERED = re.compile(r"^(\d+)-validation\.md$")
_VALIDATION_COMMIT = re.compile(r"^- \*\*Commit:\*\*\s*([0-9a-f]{7,40})\b", re.M)

# Runs a command in the checkout and returns its exit status and output.
Runner = Callable[[Sequence[str], Path], tuple[int, str]]


class RoundError(RuntimeError):
    """The view could not be opened or closed.

    The branch is never moved by a failed call. A failure after the push leaves
    the push, and after the dispatch the pipeline run, in place.
    """


@dataclass(frozen=True)
class View:
    change: str
    branch: str
    base: str
    head: str


def _run(command: Sequence[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(list(command), cwd=cwd, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise RoundError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_path(root: Path, name: str) -> Path:
    path = Path(_git(root, "rev-parse", "--git-path", name))
    return path if path.is_absolute() else root / path


def triaged_base(reviews: Path) -> str | None:
    """The commit of the latest validation record with a triage file beside it."""
    records = sorted((int(match.group(1)), entry) for entry in
                     (reviews.glob("[0-9]*-validation.md") if reviews.is_dir() else [])
                     if (match := _NUMBERED.match(entry.name))
                     and entry.with_name(entry.name.replace(".md", ".triage.md")).exists())
    for _, record in reversed(records):
        commit = _VALIDATION_COMMIT.search(record.read_text("utf-8"))
        if commit:
            return commit.group(1)
    return None


def open_view(root: Path) -> View | None:
    state = _git_path(root, STATE)
    return View(**json.loads(state.read_text("utf-8"))) if state.exists() else None


def e2e_baseline(root: Path, head: str, consume: bool = False) -> str | None:
    """The newest run before the one `start` dispatched for `head`, if it dispatched one.

    Consumed, it is forgotten, so a later validation of the same commit dispatches
    a run of its own rather than fetching this one again.
    """
    recorded = _git_path(root, E2E_BASELINES) / head
    if not recorded.exists():
        return None
    baseline = recorded.read_text("utf-8").strip()
    if consume:
        recorded.unlink()
    return baseline


def start(root: Path, change: str, base: str | None = None, e2e: bool = True,
          run: Runner = _run) -> View:
    """Push and dispatch the pipeline if asked, then reset the branch to the base."""
    if open_view(root):
        raise RoundError("a round view is already open; close it with `make round-done`")
    if not change or change == "archive" or not (root / CHANGES / change).is_dir():
        raise RoundError(f"no active change '{change}' under {CHANGES}")
    if base is None:
        base = triaged_base(root / CHANGES / change / "reviews")
        if base is None:
            raise RoundError("no triaged validation record names the previous round's "
                             "commit; give the base explicitly (BASE=<commit>)")
    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise RoundError("HEAD is detached; check out the change's branch")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise RoundError("the worktree is not clean; the view would mix other changes "
                         "into the round")
    base = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    head = _git(root, "rev-parse", "HEAD")
    if base == head:
        raise RoundError("the base is HEAD; the round has no commits to show")
    if not _ancestor(root, base, head):
        raise RoundError(f"{base[:12]} is not an ancestor of HEAD")

    if e2e:
        _dispatch(root, head, run)
    view = View(change, branch, base, head)
    # The state is written first, so a view is never open without a record of
    # the commit to return to.
    state = _git_path(root, STATE)
    state.write_text(json.dumps(asdict(view)), "utf-8")
    try:
        # -N keeps files the round added in the diff, as intent-to-add entries.
        _git(root, "reset", "--quiet", "--mixed", "-N", base)
    except RoundError:
        state.unlink()
        raise
    return view


def _dispatch(root: Path, head: str, run: Runner) -> None:
    status, output = run(["make", "--no-print-directory", "push-branch"], root)
    if status != 0:
        raise RoundError(f"the push was refused; nothing was dispatched:\n{output}")
    status, output = run(["gh", "run", "list", "--workflow", "e2e.yml", "--limit", "1",
                          "--json", "databaseId", "--jq", ".[0].databaseId"], root)
    if status != 0:
        raise RoundError(f"could not read the latest end-to-end run:\n{output}")
    baseline = output.strip() or "0"
    status, output = run(["make", "--no-print-directory", "run-e2e"], root)
    if status != 0:
        raise RoundError(f"the pipeline was not dispatched:\n{output}")
    baselines = _git_path(root, E2E_BASELINES)
    baselines.mkdir(exist_ok=True)
    (baselines / head).write_text(baseline + "\n", "utf-8")


@dataclass(frozen=True)
class Closed:
    view: View
    # Commits made on the base during the view, no longer on the branch; their
    # changes are in the worktree.
    stray: tuple[str, ...]


def done(root: Path) -> Closed:
    """Reset the branch to the round's commit, leaving the files as they are."""
    view = open_view(root)
    if view is None:
        raise RoundError("no round view is open")
    branch = _git(root, "branch", "--show-current")
    current = _git(root, "rev-parse", "HEAD")
    if branch != view.branch:
        raise RoundError(f"the view was opened on {view.branch}, but HEAD is now "
                         f"{branch or 'detached'}; switch back to {view.branch} and run "
                         "`make round-done` again. Nothing was reset")
    if current == view.head or _ancestor(root, view.head, current):
        # Already back, by hand or by an interrupted run, perhaps with commits
        # of the owner's own on top: the branch holds the round.
        _git_path(root, STATE).unlink()
        return Closed(view, ())
    if current != view.base and not _ancestor(root, view.base, current):
        raise RoundError(
            f"{branch} is at {current[:12]}, neither at or past the round's commit "
            f"{view.head} nor a descendant of its base {view.base[:12]}. Nothing was "
            f"reset; to return, `git reset --mixed {view.head}`, then run "
            "`make round-done` again")
    stray = tuple(_git(root, "rev-list", "--reverse", f"{view.head}..{current}").split())
    _git(root, "reset", "--quiet", "--mixed", view.head)
    _git_path(root, STATE).unlink()
    return Closed(view, stray)


def _ancestor(root: Path, ancestor: str, commit: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, commit],
                          cwd=root).returncode == 0


def check(root: Path) -> None:
    view = open_view(root)
    if view:
        raise RoundError(f"a round view of {view.change} is open, so the branch need not "
                         f"point at the round's commit {view.head[:12]}; run "
                         "`make round-done` first")


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    opening = actions.add_parser("start")
    opening.add_argument("change")
    opening.add_argument("--base")
    opening.add_argument("--no-e2e", action="store_true")
    actions.add_parser("done")
    actions.add_parser("check")
    actions.add_parser("e2e-baseline")
    args = parser.parse_args(argv)
    try:
        if args.action == "start":
            view = start(root, args.change, args.base, e2e=not args.no_e2e)
            print(f"Round of {view.change}: {view.base[:12]}..{view.head[:12]} is now "
                  "uncommitted changes in the checkout.")
            print(_git(root, "log", "--oneline", f"{view.base}..{view.head}"))
            if not args.no_e2e:
                print(f"Pushed {view.head[:12]} and dispatched the end-to-end pipeline; "
                      "validation fetches that run.")
            print("Read it in your editor, then `make round-done`.")
        elif args.action == "done":
            closed = done(root)
            print(f"{closed.view.branch} is back at {closed.view.head[:12]}.")
            if closed.stray:
                print("Commits made during the view are off the branch; their changes "
                      "are uncommitted below: " + ", ".join(c[:12] for c in closed.stray))
            edits = _git(root, "status", "--short")
            if edits:
                print(f"Your edits, uncommitted:\n{edits}\nValidation needs a clean "
                      "worktree: commit them as their own commit, which validation then "
                      "validates with a pipeline run of its own, or discard them.")
            else:
                print("The worktree is clean.")
        elif args.action == "check":
            check(root)
        else:
            baseline = e2e_baseline(root, _git(root, "rev-parse", "HEAD"), consume=True)
            if baseline:
                print(baseline)
    except RoundError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
