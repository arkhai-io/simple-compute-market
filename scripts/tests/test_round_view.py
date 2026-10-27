"""Tests for the round view, against real Git repositories.

What the owner sees is Git's own status of the checkout, and what the view must
preserve is Git's own state — the branch, the commits, the files — so a temporary
repository is the lowest level that proves it: a checkout of its own for a change
worked in place, and for a change worked in a clone a workspace with a bare
`origin` and the change's clone beside it. Runs in progress are injected.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import change_clone as clones
from change_workflow.running import Run

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "round_view.py"
_SPEC = importlib.util.spec_from_file_location("round_view", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
rounds = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = rounds
_SPEC.loader.exec_module(rounds)

CHANGE = "the-change"
BRANCH = f"feat/{CHANGE}"
REVIEWS = Path("openspec/changes") / CHANGE / "reviews"
PROSE = "a\nb\nc\nd\ne\n"
ROUND = "A\nb\nc\nd\ne\n"     # the round's change, to the first line
EDITED = "A\nb\nc\nd\nE\n"    # the round's version with the owner's edit to the last


def _no_runs(_: Path) -> list[Run]:
    return []


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def _write(repo: Path, files: dict[str, str | bytes | None], message: str = "commit") -> str:
    for name, text in files.items():
        target = repo / name
        if text is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            target.write_bytes(text)
        else:
            target.write_text(text, "utf-8")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _validation(repo: Path, number: int, commit: str, *, triaged: bool) -> None:
    reviews = repo / REVIEWS
    reviews.mkdir(parents=True, exist_ok=True)
    (reviews / f"{number:02d}-validation.md").write_text(
        f"# Validation\n\n- **Commit:** {commit} on feat/change\n- **Result:** passed\n", "utf-8")
    if triaged:
        (reviews / f"{number:02d}-validation.triage.md").write_text("# Triage\n", "utf-8")


def _round_line(repo: Path, commit: str | None) -> None:
    reviews = repo / REVIEWS
    reviews.mkdir(parents=True, exist_ok=True)
    line = {"seq": 1, "step": "orchestrator", "outcome": "round", "sections": [[2]],
            "by": "plan", "after": 0, **({"commit": commit} if commit else {})}
    with (reviews / "workflow.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(line) + "\n")


def _status(repo: Path) -> set[str]:
    return {line.strip() for line in _git(repo, "status", "--porcelain").splitlines()}


BASE_FILES: dict[str, str | bytes | None] = {
    "src/kept.py": "1\n", "src/gone.py": "gone\n", "src/prose.txt": PROSE,
    "src/blob.bin": b"\0base", f"openspec/changes/{CHANGE}/notes.txt": "1\n"}
ROUND_FILES: dict[str, str | bytes | None] = {
    "src/kept.py": "2\n", "src/gone.py": None, "src/new.py": "new\n", "src/prose.txt": ROUND,
    "src/blob.bin": b"\0round"}
ROUND_STATUS = {"M src/kept.py", "D src/gone.py", "A src/new.py", "M src/prose.txt",
                "M src/blob.bin"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", BRANCH, str(work))
    # Reviews are untracked, as in the repository.
    (work / ".gitignore").write_text("reviews/\n", "utf-8")
    _write(work, BASE_FILES)
    return work


def _round(repo: Path) -> tuple[str, str]:
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, {k: v for k, v in ROUND_FILES.items() if k != "src/new.py"})
    head = _write(repo, {"src/new.py": "new\n"})
    return base, head


def _start(repo: Path, base: str | None = None, runs=_no_runs) -> "rounds.View":
    return rounds.start(repo, CHANGE, base=base, runs=runs)


# A change worked in its own checkout: the branch reset in place.

def test_the_round_shows_as_uncommitted_changes_with_the_files_unchanged(repo: Path) -> None:
    base, head = _round(repo)

    view = _start(repo, base)

    assert (view.base, view.head, view.clone) == (base, head, None)
    assert _git(repo, "rev-parse", "HEAD") == base
    assert _git(repo, "branch", "--show-current") == BRANCH
    assert _status(repo) == ROUND_STATUS
    assert (repo / "src/new.py").read_text("utf-8") == "new\n"
    assert "src/new.py" in _git(repo, "diff", "--name-only")


def test_done_restores_the_commit_and_keeps_the_owners_edits(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    (repo / "src/kept.py").write_text("edited while reading\n", "utf-8")

    closed = rounds.done(repo)

    assert (closed.carried, closed.returned_to, closed.stayed) == ((), None, None)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _status(repo) == {"M src/kept.py"}
    assert rounds.open_view(repo) is None


def test_done_without_edits_leaves_a_clean_worktree(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)

    rounds.done(repo)

    assert _git(repo, "rev-parse", "HEAD") == head
    assert _status(repo) == set()


def test_done_leaves_no_phantom_edit_for_an_empty_file_the_round_added(repo: Path) -> None:
    """An intent-to-add entry for an empty file records the empty blob, which is
    also what the round's commit records, so a reset alone keeps its flag and
    the unchanged file reads as an edit."""
    base = _git(repo, "rev-parse", "HEAD")
    head = _write(repo, {"tests/integration/__init__.py": ""})
    _start(repo, base)

    rounds.done(repo)

    assert _git(repo, "rev-parse", "HEAD") == head
    assert _status(repo) == set()


def test_the_base_is_the_latest_triaged_validation(repo: Path) -> None:
    first = _git(repo, "rev-parse", "HEAD")
    second = _write(repo, {"src/kept.py": "2\n"})
    _write(repo, {"src/kept.py": "3\n"})
    _validation(repo, 3, first, triaged=True)
    _validation(repo, 5, second, triaged=True)
    _validation(repo, 7, _git(repo, "rev-parse", "HEAD"), triaged=False)

    assert _start(repo).base == second


def test_the_base_is_the_commit_the_latest_round_started_at(repo: Path) -> None:
    validated = _git(repo, "rev-parse", "HEAD")
    _validation(repo, 3, validated, triaged=True)
    # A design revision lands on the branch between the rounds.
    started = _write(repo, {f"openspec/changes/{CHANGE}/notes.txt": "revised\n"})
    _round_line(repo, started)
    _write(repo, {"src/kept.py": "2\n"})

    assert _start(repo).base == started


def test_a_round_line_naming_no_commit_falls_back_to_the_triaged_validation(
        repo: Path) -> None:
    validated = _git(repo, "rev-parse", "HEAD")
    _validation(repo, 3, validated, triaged=True)
    _round_line(repo, _write(repo, {"src/kept.py": "2\n"}))
    _round_line(repo, None)
    _write(repo, {"src/kept.py": "3\n"})

    assert _start(repo).base == validated


def test_with_no_triaged_validation_the_base_must_be_given(repo: Path) -> None:
    _write(repo, {"src/kept.py": "2\n"})
    with pytest.raises(rounds.RoundError, match="BASE="):
        _start(repo)


def test_steps_that_describe_a_commit_refuse_while_the_view_is_open(repo: Path) -> None:
    base, _ = _round(repo)
    rounds.check(repo)
    _start(repo, base)
    with pytest.raises(rounds.RoundError, match="round-done"):
        rounds.check(repo)
    with pytest.raises(rounds.RoundError, match="already open"):
        _start(repo, base)


def test_a_view_already_back_at_the_round_is_closed(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    _git(repo, "reset", "-q", "--mixed", head)

    closed = rounds.done(repo)

    assert closed.carried == ()
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None
    rounds.check(repo)


def test_a_fix_committed_after_returning_by_hand_stays_on_the_branch(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    _git(repo, "reset", "-q", "--mixed", head)
    fix = _write(repo, {"src/kept.py": "fixed\n"})

    closed = rounds.done(repo)

    assert closed.carried == ()
    assert _git(repo, "rev-parse", "HEAD") == fix
    assert _status(repo) == set()


def test_a_branch_reset_to_a_round_commit_carries_nothing(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    middle = _write(repo, {"src/kept.py": "2\n"})
    head = _write(repo, {"src/new.py": "new\n"})
    _start(repo, base)
    _git(repo, "reset", "-q", "--mixed", middle)

    closed = rounds.done(repo)

    assert closed.carried == ()
    assert _git(repo, "rev-parse", "HEAD") == head


def test_a_view_recorded_but_never_reset_is_closed(repo: Path) -> None:
    base, head = _round(repo)
    # An interrupted start: the state written, the branch not yet moved.
    rounds._write_state(repo, rounds.View(CHANGE, BRANCH, base, head))

    rounds.done(repo)

    assert _git(repo, "rev-parse", "HEAD") == head
    assert _status(repo) == set()
    assert rounds.open_view(repo) is None


def test_done_refuses_on_another_branch_and_keeps_the_view(repo: Path) -> None:
    base, _ = _round(repo)
    _start(repo, base)
    _git(repo, "switch", "-q", "-c", "elsewhere")

    with pytest.raises(rounds.RoundError, match=f"switch back to {BRANCH}"):
        rounds.done(repo)
    assert rounds.open_view(repo) is not None
    assert _git(repo, "rev-parse", "HEAD") == base


def test_done_refuses_a_branch_moved_off_the_base_and_names_the_way_back(
        repo: Path) -> None:
    root = _git(repo, "rev-parse", "HEAD")
    base = _write(repo, {"src/kept.py": "base\n"})
    head = _write(repo, {"src/kept.py": "2\n"})
    _start(repo, base)
    _git(repo, "reset", "-q", "--mixed", root)

    with pytest.raises(rounds.RoundError, match=f"git reset --mixed {head}"):
        rounds.done(repo)
    assert _git(repo, "rev-parse", "HEAD") == root
    assert rounds.open_view(repo) is not None


@pytest.mark.parametrize("dirty", ["src/kept.py", "untracked.txt"])
def test_a_dirty_worktree_is_refused_naming_it_and_nothing_moves(repo: Path,
                                                                 dirty: str) -> None:
    base, head = _round(repo)
    (repo / dirty).write_text("mine\n", "utf-8")
    with pytest.raises(rounds.RoundError, match=f"(?s)not clean.*{dirty}"):
        _start(repo, base)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None


def test_a_checkout_with_a_run_in_progress_is_refused_naming_it(repo: Path) -> None:
    base, head = _round(repo)
    running = Run(4242, "implement", CHANGE, "2026-10-20T10:00:00Z")

    with pytest.raises(rounds.RoundError, match=r"implement of the-change \(process 4242"):
        _start(repo, base, runs=lambda _: [running])
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None


def test_a_base_that_is_not_an_ancestor_is_refused(repo: Path) -> None:
    root = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "elsewhere")
    other = _write(repo, {"src/other.py": "other\n"})
    _git(repo, "checkout", "-q", BRANCH)
    _git(repo, "reset", "-q", "--hard", root)
    head = _write(repo, {"src/kept.py": "2\n"})
    with pytest.raises(rounds.RoundError, match="not an ancestor"):
        _start(repo, other)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None


def test_a_detached_head_or_an_empty_round_is_refused(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(rounds.RoundError, match="no commits to show"):
        _start(repo, head)
    assert _git(repo, "rev-parse", "HEAD") == head
    later = _write(repo, {"src/kept.py": "2\n"})
    _git(repo, "checkout", "-q", "--detach")
    with pytest.raises(rounds.RoundError, match="detached"):
        _start(repo, head)
    assert _git(repo, "rev-parse", "HEAD") == later
    assert rounds.open_view(repo) is None


@pytest.mark.parametrize("change", ["", "archive", "missing"])
def test_an_unknown_change_is_refused(repo: Path, change: str) -> None:
    (repo / "openspec/changes/archive").mkdir()
    head = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(rounds.RoundError, match="not a change name|no change"):
        rounds.start(repo, change, base="HEAD", runs=_no_runs)
    assert _git(repo, "rev-parse", "HEAD") == head
    assert rounds.open_view(repo) is None


def test_an_archived_change_takes_its_base_from_the_archive(repo: Path) -> None:
    base, _ = _round(repo)
    archived = repo / "openspec/changes/archive" / f"2026-10-14-{CHANGE}"
    archived.parent.mkdir()
    (repo / "openspec/changes" / CHANGE).rename(archived)
    (archived / "reviews").mkdir()
    (archived / "reviews/01-validation.md").write_text(
        f"# Validation\n\n- **Commit:** {base}\n- **Result:** passed\n", "utf-8")
    (archived / "reviews/01-validation.triage.md").write_text("# Triage\n", "utf-8")
    head = _write(repo, {})  # commits the archive's move

    view = _start(repo)

    assert (view.base, view.head) == (base, head)


def test_the_command_line_guard_fails_while_a_view_is_open(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, _ = _round(repo)
    assert rounds.main(["check"], root=repo) == 0
    assert rounds.main(["start", CHANGE, "--base", base], root=repo) == 0
    assert rounds.main(["check"], root=repo) == 1
    assert "round-done" in capsys.readouterr().err
    assert rounds.main(["done"], root=repo) == 0
    assert rounds.main(["check"], root=repo) == 0


# Carrying commits made during the view onto the round's commit.

def _commit_as_owner(repo: Path, *paths: str, message: str = "the owner's edit",
                     staged: bool = False) -> str:
    """Commit as the owner would during the view: the paths given, what is already
    staged, or else `-a`."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "owner",
           "GIT_AUTHOR_EMAIL": "owner@example.invalid", "GIT_AUTHOR_DATE": "1700000000 +0100"}
    if paths:
        subprocess.run(["git", "add", "--", *paths], cwd=repo, check=True, env=env)
    if paths or staged:
        command = ["git", "commit", "-q", "-m", message]
    else:
        command = ["git", "commit", "-q", "-a", "-m", message]
    subprocess.run(command, cwd=repo, check=True, env=env)
    return _git(repo, "rev-parse", "HEAD")


def _show(repo: Path, commit: str, path: str) -> str | None:
    shown = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repo, capture_output=True,
                           text=True)
    return shown.stdout if shown.returncode == 0 else None


def test_a_commit_of_an_edit_is_carried_onto_the_round_with_its_author_and_message(
        repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    (repo / "src/fresh.txt").write_text("the owner's\n", "utf-8")
    original = _commit_as_owner(repo, "src/fresh.txt")

    closed = rounds.done(repo)

    (carried,) = closed.carried
    assert carried.original == original
    replacement = carried.replacement
    assert _git(repo, "rev-parse", "HEAD") == replacement
    assert _git(repo, "rev-parse", f"{replacement}^") == head
    assert _git(repo, "show", "-s", "--format=%an <%ae> %ad%n%B", "--date=raw",
                replacement) == "owner <owner@example.invalid> 1700000000 +0100\nthe owner's edit"
    assert _git(repo, "diff", "--name-only", head, replacement) == "src/fresh.txt"
    assert _status(repo) == set()
    assert rounds.open_view(repo) is None


def test_a_whole_file_committed_then_edited_on_is_carried_and_the_edit_kept(
        repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    (repo / "src/prose.txt").write_text(EDITED, "utf-8")
    _commit_as_owner(repo, "src/prose.txt")
    (repo / "src/prose.txt").write_text(EDITED + "more\n", "utf-8")

    closed = rounds.done(repo)

    replacement = closed.carried[0].replacement
    assert _show(repo, replacement, "src/prose.txt") == EDITED
    assert _git(repo, "diff", "--name-only", head, replacement) == "src/prose.txt"
    assert _status(repo) == {"M src/prose.txt"}
    assert (repo / "src/prose.txt").read_text("utf-8") == EDITED + "more\n"


def test_commit_all_carries_the_owners_edits_and_nothing_else(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    (repo / "src/prose.txt").write_text(EDITED, "utf-8")
    _commit_as_owner(repo)

    replacement = rounds.done(repo).carried[0].replacement

    assert _git(repo, "diff", "--name-only", head, replacement) == "src/prose.txt"


def test_several_commits_are_carried_oldest_first(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    (repo / "src/prose.txt").write_text(EDITED, "utf-8")
    first = _commit_as_owner(repo, "src/prose.txt", message="first")
    (repo / "src/fresh.txt").write_text("second\n", "utf-8")
    second = _commit_as_owner(repo, "src/fresh.txt", message="second")

    carried = rounds.done(repo).carried

    assert [c.original for c in carried] == [first, second]
    assert _git(repo, "rev-parse", f"{carried[1].replacement}^") == carried[0].replacement
    assert _git(repo, "rev-parse", f"{carried[0].replacement}^") == head
    assert _git(repo, "diff", "--name-only", head, carried[1].replacement).split() == [
        "src/fresh.txt", "src/prose.txt"]


def test_a_committed_deletion_the_round_made_is_carried(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    _git(repo, "rm", "-q", "--cached", "src/gone.py")
    original = _commit_as_owner(repo, message="drop gone.py", staged=True)
    (repo / "src/fresh.txt").write_text("the owner's\n", "utf-8")
    _commit_as_owner(repo, "src/fresh.txt")

    first, second = rounds.done(repo).carried

    # The deletion is already the round's, so its commit holds nothing to carry.
    assert (first.original, first.replacement) == (original, None)
    assert _git(repo, "rev-parse", f"{second.replacement}^") == head
    assert _show(repo, second.replacement, "src/gone.py") is None
    assert _git(repo, "diff", "--name-only", head, second.replacement) == "src/fresh.txt"


def test_a_commit_holding_nothing_beyond_the_round_is_dropped_and_named(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, head = _round(repo)
    _start(repo, base)
    original = _commit_as_owner(repo, message="commit all, no edit")

    assert rounds.main(["done"], root=repo) == 0

    assert _git(repo, "rev-parse", "HEAD") == head
    assert f"Dropped {original[:12]}" in capsys.readouterr().out


def test_done_names_each_original_beside_its_replacement(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, _ = _round(repo)
    _start(repo, base)
    (repo / "src/fresh.txt").write_text("the owner's\n", "utf-8")
    original = _commit_as_owner(repo, "src/fresh.txt")

    assert rounds.main(["done"], root=repo) == 0

    replacement = _git(repo, "rev-parse", "HEAD")
    assert (f"Carried {original[:12]}, made during the view, onto it as {replacement[:12]}."
            in capsys.readouterr().out)


@pytest.mark.parametrize("how", ["round change left unstaged", "round change removed"])
def test_a_commit_lacking_a_round_change_to_a_file_is_refused(repo: Path, how: str) -> None:
    base, head = _round(repo)
    _start(repo, base)
    lacking = "a\nb\nc\nd\nE\n"
    if how == "round change left unstaged":
        # `git add -p` of the owner's hunk alone: the index keeps the base's line.
        (repo / "src/prose.txt").write_text(lacking, "utf-8")
        _git(repo, "add", "src/prose.txt")
        (repo / "src/prose.txt").write_text(EDITED, "utf-8")
        _commit_as_owner(repo, message="part of the file", staged=True)
    else:
        (repo / "src/prose.txt").write_text(lacking, "utf-8")
        _commit_as_owner(repo, "src/prose.txt", message="the round's line undone")
    made = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(rounds.RoundError, match=f"src/prose.txt.*git reset --mixed {head}"):
        rounds.done(repo)
    assert _git(repo, "rev-parse", "HEAD") == made
    assert _git(repo, "rev-parse", "HEAD^") == base
    assert rounds.open_view(repo) is not None


def test_an_edit_inside_a_line_the_round_changed_is_refused(repo: Path) -> None:
    base, _ = _round(repo)
    _start(repo, base)
    (repo / "src/prose.txt").write_text("A, said the owner\nb\nc\nd\ne\n", "utf-8")
    _commit_as_owner(repo, "src/prose.txt")

    with pytest.raises(rounds.RoundError, match="src/prose.txt.*conflicts"):
        rounds.done(repo)


@pytest.mark.parametrize("how,refusal", [
    ("deleted", "src/prose.txt: the round changed it, and the commit deletes it"),
    ("made executable", "src/prose.txt: the round changed it, and the commit changes its mode"),
])
def test_a_text_file_the_round_changed_is_refused_deleted_or_with_another_mode(
        repo: Path, how: str, refusal: str) -> None:
    base, _ = _round(repo)
    _start(repo, base)
    if how == "deleted":
        _git(repo, "rm", "-q", "--cached", "src/prose.txt")
        _commit_as_owner(repo, message="prose dropped", staged=True)
    else:
        (repo / "src/prose.txt").chmod(0o755)
        _commit_as_owner(repo, "src/prose.txt", message="prose made executable")

    with pytest.raises(rounds.RoundError, match=refusal):
        rounds.done(repo)


def test_an_edited_file_the_round_added_is_refused(repo: Path) -> None:
    base, _ = _round(repo)
    _start(repo, base)
    (repo / "src/new.py").write_text("new, edited\n", "utf-8")
    _commit_as_owner(repo, "src/new.py")

    with pytest.raises(rounds.RoundError, match="src/new.py: the round added it"):
        rounds.done(repo)
    assert rounds.open_view(repo) is not None


def test_a_binary_file_is_carried_only_as_the_round_left_it(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    _commit_as_owner(repo, "src/blob.bin", message="the round's binary")
    (repo / "src/blob.bin").write_bytes(b"\0owner")
    _commit_as_owner(repo, "src/blob.bin", message="the owner's binary")

    with pytest.raises(rounds.RoundError,
                       match="src/blob.bin: the round changed it as a binary file"):
        rounds.done(repo)

    _git(repo, "reset", "-q", "--mixed", "HEAD^")
    (repo / "src/blob.bin").write_bytes(b"\0round")
    # The round's binary beside an edit of the owner's, in one commit.
    (repo / "src/fresh.txt").write_text("the owner's\n", "utf-8")
    _git(repo, "add", "src/fresh.txt")
    _git(repo, "commit", "-q", "--amend", "--no-edit")
    (carried,) = rounds.done(repo).carried
    assert _show(repo, carried.replacement, "src/fresh.txt") == "the owner's\n"
    assert _git(repo, "diff", "--name-only", head, carried.replacement) == "src/fresh.txt"


def test_a_link_or_a_mode_the_round_changed_is_carried_only_as_the_round_left_it(
        repo: Path) -> None:
    (repo / "src/link").symlink_to("kept.py")
    base = _write(repo, {})
    (repo / "src/link").unlink()
    (repo / "src/link").symlink_to("gone.py")
    (repo / "src/kept.py").chmod(0o755)
    head = _write(repo, {})
    _start(repo, base)
    (repo / "src/fresh.txt").write_text("the owner's\n", "utf-8")
    _commit_as_owner(repo, "src/link", "src/kept.py", "src/fresh.txt",
                     message="the round's link and mode, and an edit")
    carried = rounds.done(repo).carried[0].replacement
    assert _git(repo, "diff", "--name-only", head, carried) == "src/fresh.txt"


def test_a_mode_the_round_changed_and_the_commit_undid_is_refused(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "src/kept.py").chmod(0o755)
    _write(repo, {})
    _start(repo, base)
    (repo / "src/kept.py").chmod(0o644)
    (repo / "src/kept.py").write_text("1\nthe owner's\n", "utf-8")
    _commit_as_owner(repo, "src/kept.py", message="an edit, the mode undone")

    with pytest.raises(rounds.RoundError, match="src/kept.py: the round changed it as a "
                                                "binary file, a link, or a mode"):
        rounds.done(repo)


def test_a_merge_made_during_the_view_is_refused(repo: Path) -> None:
    base, _ = _round(repo)
    _start(repo, base)
    _commit_as_owner(repo, "src/kept.py", message="first")
    _git(repo, "worktree", "add", "-q", "-b", "side", str(repo.parent / "side"), base)
    side = _write(repo.parent / "side", {"src/side.txt": "side\n"})
    # A merge commit on the branch, the worktree left as the view has it.
    merge = _git(repo, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-p", side, "-m", "merge")
    _git(repo, "update-ref", "HEAD", merge)

    with pytest.raises(rounds.RoundError, match=f"{merge[:12]}.*is a merge"):
        rounds.done(repo)
    assert _git(repo, "rev-parse", "HEAD") == merge


def test_a_merge_bringing_in_the_rounds_commit_is_refused(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    (repo / "src/fresh.txt").write_text("the owner's\n", "utf-8")
    made = _commit_as_owner(repo, "src/fresh.txt")
    # An editor's sync, say, merging the pushed branch into the owner's commit.
    merge = _git(repo, "commit-tree", f"{head}^{{tree}}", "-p", made, "-p", head, "-m", "sync")
    _git(repo, "update-ref", "HEAD", merge)

    with pytest.raises(rounds.RoundError, match=f"{made[:12]}.*was merged"):
        rounds.done(repo)
    assert _git(repo, "rev-parse", "HEAD") == merge
    assert rounds.open_view(repo) is not None


def test_a_reset_into_the_round_then_a_commit_is_refused_as_leaving_the_line(
        repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    middle = _write(repo, {"src/kept.py": "2\n"})
    head = _write(repo, {"src/new.py": "new\n"})
    _start(repo, base)
    _git(repo, "reset", "-q", "--mixed", middle)
    (repo / "src/fresh.txt").write_text("the owner's\n", "utf-8")
    _commit_as_owner(repo, "src/fresh.txt")

    with pytest.raises(rounds.RoundError, match=f"left the line.*git reset --mixed {head}"):
        rounds.done(repo)


def test_an_amended_base_is_refused_as_leaving_the_line(repo: Path) -> None:
    base, head = _round(repo)
    _start(repo, base)
    _git(repo, "commit", "-q", "--amend", "-m", "the base, amended")

    with pytest.raises(rounds.RoundError, match=f"left the line.*git reset --mixed {head}"):
        rounds.done(repo)
    assert rounds.open_view(repo) is not None


# A change worked in its own clone: read in the owner's workspace.

def _spawned(command, cwd: Path, log: Path, status: Path) -> int:
    log.write_text("", "utf-8")
    status.write_text("0\n", "utf-8")
    return os.getpid()


@pytest.fixture
def cloned(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """A workspace on `dev`, and the change's clone with a committed round."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "dev", str(work))
    (work / ".gitignore").write_text("reviews/\n.claude/settings.local.json\n", "utf-8")
    base = _write(work, BASE_FILES)
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "dev")
    clone = clones.create(work, CHANGE, spawn=_spawned).clone
    _round_line(clone, base)
    head = _write(clone, ROUND_FILES)
    return work, clone, base, head


def test_a_round_from_a_clone_is_read_in_the_workspace_on_the_branch_by_name(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, clone, base, head = cloned

    view = _start(work)

    assert (view.base, view.head, view.branch) == (base, head, BRANCH)
    assert (view.clone, view.returns_to, view.detached) == (str(clone), "dev", False)
    assert _git(work, "branch", "--show-current") == BRANCH
    assert _git(work, "rev-parse", "HEAD") == base
    assert _status(work) == ROUND_STATUS
    # The clone, where every step runs, never moves.
    assert (_git(clone, "rev-parse", "HEAD"), _status(clone)) == (head, set())
    rounds.check(clone)
    with pytest.raises(rounds.RoundError, match="round-done"):
        rounds.check(work)


def test_done_puts_the_branch_back_and_the_workspace_where_it_was(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, clone, _, head = cloned
    _start(work)

    closed = rounds.done(work)

    assert (closed.returned_to, closed.stayed) == ("dev", None)
    assert _git(work, "branch", "--show-current") == "dev"
    assert _git(work, "rev-parse", BRANCH) == head
    assert _status(work) == set()
    assert _git(clone, "rev-parse", "HEAD") == head


def test_a_detached_workspace_is_returned_to_its_commit(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, base, _ = cloned
    _git(work, "checkout", "-q", "--detach")
    _start(work)

    assert rounds.done(work).returned_to == base
    assert _git(work, "rev-parse", "HEAD") == base
    assert _git(work, "branch", "--show-current") == ""


def test_an_owners_commit_is_carried_and_left_in_the_workspace_for_triage_to_pull(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, clone, _, head = cloned
    _start(work)
    (work / "src/prose.txt").write_text(EDITED, "utf-8")
    _commit_as_owner(work, "src/prose.txt")

    closed = rounds.done(work)

    replacement = closed.carried[0].replacement
    assert _git(work, "rev-parse", BRANCH) == replacement
    assert _git(work, "rev-parse", f"{replacement}^") == head
    assert _git(work, "branch", "--show-current") == "dev"
    assert _git(clone, "rev-parse", "HEAD") == head
    # Triage's pull is a fast-forward.
    _git(clone, "pull", "-q", "--ff-only", "workspace", BRANCH)
    assert _git(clone, "rev-parse", "HEAD") == replacement


def test_uncommitted_edits_keep_the_workspace_on_the_changes_branch(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, _, head = cloned
    _start(work)
    (work / "src/prose.txt").write_text(EDITED, "utf-8")

    closed = rounds.done(work)

    assert closed.returned_to is None and "git checkout dev" in (closed.stayed or "")
    assert _git(work, "branch", "--show-current") == BRANCH
    assert _git(work, "rev-parse", "HEAD") == head
    assert _status(work) == {"M src/prose.txt"}


def test_the_workspace_branch_is_fast_forwarded_and_one_ahead_of_the_clone_refused(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, base, head = cloned
    _git(work, "branch", BRANCH, base)
    assert _start(work).head == head
    rounds.done(work)

    _git(work, "switch", "-q", BRANCH)
    mine = _write(work, {"src/mine.txt": "mine\n"})
    _git(work, "switch", "-q", "dev")
    with pytest.raises(rounds.RoundError, match="holds commits the clone's .* lacks"):
        _start(work)
    assert (_git(work, "rev-parse", BRANCH), _git(work, "branch", "--show-current")) == (
        mine, "dev")
    assert rounds.open_view(work) is None


def test_a_workspace_with_uncommitted_changes_is_refused_naming_them(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, _, _ = cloned
    (work / "src/kept.py").write_text("mine\n", "utf-8")

    with pytest.raises(rounds.RoundError, match="src/kept.py"):
        _start(work)
    assert _git(work, "branch", "--show-current") == "dev"
    assert rounds.open_view(work) is None


def test_a_workspace_with_a_run_in_progress_is_refused_naming_it(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, _, _ = cloned
    # A step of another change worked in the workspace itself.
    running = Run(4242, "validate", "another-change", "2026-10-20T10:00:00Z")

    with pytest.raises(rounds.RoundError, match="validate of another-change"):
        _start(work, runs=lambda _: [running])
    assert _git(work, "branch", "--show-current") == "dev"
    assert rounds.open_view(work) is None


def test_another_changes_open_view_is_refused_naming_it(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, base, head = cloned
    rounds._write_state(work, rounds.View("other-change", "feat/other-change", base, head))

    with pytest.raises(rounds.RoundError, match="view of other-change is open"):
        _start(work)
    assert _git(work, "branch", "--show-current") == "dev"


def test_a_view_cannot_be_opened_in_the_clone(cloned: tuple[Path, Path, str, str]) -> None:
    _, clone, _, head = cloned

    with pytest.raises(rounds.RoundError, match="read the round in the owner's workspace"):
        rounds.start(clone, CHANGE, runs=_no_runs)
    assert _git(clone, "rev-parse", "HEAD") == head


def test_the_view_is_refreshed_onto_a_triage_fix_over_the_same_base(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, clone, base, _ = cloned
    _start(work)
    fix = _write(clone, {"src/kept.py": "3\n"}, message="triage's fix")

    view = _start(work)

    assert (view.base, view.head) == (base, fix)
    assert _git(work, "rev-parse", "HEAD") == base
    assert (work / "src/kept.py").read_text("utf-8") == "3\n"
    assert "M src/kept.py" in _status(work)
    rounds.done(work)
    assert _git(work, "rev-parse", BRANCH) == fix
    assert _git(clone, "rev-parse", "HEAD") == fix


def test_a_refresh_is_refused_over_edits_made_during_the_view(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, clone, _, head = cloned
    _start(work)
    (work / "src/prose.txt").write_text(EDITED, "utf-8")
    _write(clone, {"src/kept.py": "3\n"})

    with pytest.raises(rounds.RoundError, match="src/prose.txt.*round-done"):
        _start(work)
    assert rounds.open_view(work).head == head
    assert (work / "src/prose.txt").read_text("utf-8") == EDITED


def test_a_workspace_already_on_the_branch_is_fast_forwarded_and_returned_to_it(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, base, head = cloned
    _git(work, "switch", "-q", "-c", BRANCH)

    view = _start(work)

    assert (view.head, view.returns_to, _git(work, "rev-parse", "HEAD")) == (head, BRANCH, base)
    assert rounds.done(work).returned_to == BRANCH
    assert _git(work, "rev-parse", "HEAD") == head


def test_a_workspace_branch_diverged_from_the_clones_is_refused(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, base, _ = cloned
    _git(work, "switch", "-q", "-c", BRANCH, base)
    mine = _write(work, {"src/mine.txt": "mine\n"})
    _git(work, "switch", "-q", "dev")

    with pytest.raises(rounds.RoundError, match="or has diverged from it"):
        _start(work)
    assert _git(work, "rev-parse", BRANCH) == mine
    assert rounds.open_view(work) is None


def test_a_refresh_onto_a_head_not_descending_from_the_views_is_refused(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, clone, base, head = cloned
    _start(work)
    _git(clone, "reset", "-q", "--hard", base)
    _write(clone, {"src/kept.py": "rewritten\n"})

    with pytest.raises(rounds.RoundError, match="no longer descends"):
        _start(work)
    assert rounds.open_view(work).head == head
    assert _git(work, "rev-parse", "HEAD") == base


def test_a_refresh_is_refused_with_a_run_in_progress(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, clone, _, head = cloned
    _start(work)
    _write(clone, {"src/kept.py": "3\n"})
    running = Run(4242, "design", "another-change", "2026-10-20T10:00:00Z")

    with pytest.raises(rounds.RoundError, match="design of another-change"):
        _start(work, runs=lambda _: [running])
    assert rounds.open_view(work).head == head


def test_a_refresh_with_nothing_new_leaves_the_view_as_it_is(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, base, head = cloned
    opened = _start(work)

    assert _start(work) == opened
    assert (_git(work, "rev-parse", "HEAD"), _status(work)) == (base, ROUND_STATUS)
    assert rounds.open_view(work).head == head


def test_a_refresh_names_a_branch_moved_back_to_the_round_by_hand(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, _, head = cloned
    _start(work)
    _git(work, "reset", "-q", "--mixed", head)

    with pytest.raises(rounds.RoundError, match=f"moved off the round's base, to {head[:12]}"):
        _start(work)


def test_done_is_refused_while_a_run_is_in_progress(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, base, _ = cloned
    _start(work)
    running = Run(4242, "plan", "another-change", "2026-10-20T10:00:00Z")

    with pytest.raises(rounds.RoundError, match="plan of another-change"):
        rounds.done(work, runs=lambda _: [running])
    assert (_git(work, "branch", "--show-current"), _git(work, "rev-parse", "HEAD")) == (
        BRANCH, base)
    assert rounds.open_view(work) is not None


def test_a_refresh_keeps_its_base(cloned: tuple[Path, Path, str, str]) -> None:
    work, _, base, _ = cloned
    _start(work)

    with pytest.raises(rounds.RoundError, match="a refresh keeps its base"):
        _start(work, base)


def test_a_refresh_is_refused_over_a_commit_made_during_the_view(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, _, head = cloned
    _start(work)
    (work / "src/prose.txt").write_text(EDITED, "utf-8")
    made = _commit_as_owner(work, "src/prose.txt")

    with pytest.raises(rounds.RoundError, match=f"{made[:12]}.*round-done"):
        _start(work)
    assert rounds.open_view(work).head == head


# An ignored file where the commit a move goes to tracks one: Git would overwrite
# it without a word, and holds no copy of it.

MINE = "the owner's own\n"


def _ignored(work: Path, path: str) -> None:
    """An ignored file of the owner's in the workspace, ignored there alone."""
    with (work / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write(f"/{path}\n")
    (work / path).parent.mkdir(parents=True, exist_ok=True)
    (work / path).write_text(MINE, "utf-8")


@pytest.mark.parametrize("on_branch", [False, True], ids=["by checkout", "by fast-forward"])
def test_opening_is_refused_over_an_ignored_file_the_round_tracks(
        cloned: tuple[Path, Path, str, str], on_branch: bool) -> None:
    work, clone, base, _ = cloned
    _write(clone, {"local.cfg": "tracked\n"})
    if on_branch:
        _git(work, "switch", "-q", "-c", BRANCH, base)
    _ignored(work, "local.cfg")

    with pytest.raises(rounds.RoundError, match="local.cfg; move it aside"):
        _start(work)

    assert (work / "local.cfg").read_text("utf-8") == MINE
    assert _git(work, "branch", "--show-current") == (BRANCH if on_branch else "dev")
    assert _git(work, "rev-parse", "HEAD") == base
    assert rounds.open_view(work) is None
    if not on_branch:
        assert _git(work, "branch", "--list", BRANCH) == ""


def test_a_refresh_is_refused_over_an_ignored_file_the_fix_tracks(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, clone, base, head = cloned
    _start(work)
    _write(clone, {"local.cfg": "tracked\n"}, message="triage's fix")
    _ignored(work, "local.cfg")

    with pytest.raises(rounds.RoundError, match="local.cfg; move it aside"):
        _start(work)

    assert (work / "local.cfg").read_text("utf-8") == MINE
    assert rounds.open_view(work).head == head
    assert (_git(work, "rev-parse", "HEAD"), _status(work)) == (base, ROUND_STATUS)


def test_the_return_is_skipped_over_an_ignored_file_where_it_tracks_one(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, _, head = cloned
    _start(work)
    # The round deleted it; `dev`, where the workspace returns, still tracks it.
    _ignored(work, "src/gone.py")

    closed = rounds.done(work)

    assert closed.returned_to is None and "src/gone.py" in (closed.stayed or "")
    assert (work / "src/gone.py").read_text("utf-8") == MINE
    assert (_git(work, "branch", "--show-current"), _git(work, "rev-parse", "HEAD")) == (
        BRANCH, head)
    assert rounds.open_view(work) is None


def test_an_ignored_file_where_the_round_tracks_nothing_moves_freely(
        cloned: tuple[Path, Path, str, str]) -> None:
    work, _, _, head = cloned
    _ignored(work, "scratch.txt")

    _start(work)
    closed = rounds.done(work)

    assert closed.returned_to == "dev"
    assert (work / "scratch.txt").read_text("utf-8") == MINE


def test_a_file_the_target_replaces_with_a_directory_is_not_in_the_way(repo: Path) -> None:
    current = _write(repo, {"conf": "a file\n"})
    _git(repo, "rm", "-q", "conf")
    target = _write(repo, {"conf/x": "now a directory\n"})
    _git(repo, "checkout", "-q", current)

    assert rounds._in_the_way(repo, current, target) == []


def test_an_ignored_file_where_the_target_puts_a_directory_is_in_the_way(repo: Path) -> None:
    current = _git(repo, "rev-parse", "HEAD")
    target = _write(repo, {"cfg/x": "tracked\n"})
    _git(repo, "checkout", "-q", current)
    _ignored(repo, "cfg")

    assert rounds._in_the_way(repo, current, target) == ["cfg/x"]


@pytest.mark.parametrize("ignored", [False, True], ids=["tracked files only", "an ignored file"])
def test_a_directory_the_target_replaces_with_a_file_is_in_the_way_only_when_it_holds_more(
        repo: Path, ignored: bool) -> None:
    current = _write(repo, {"dir/tracked": "1\n"})
    _git(repo, "rm", "-q", "dir/tracked")
    target = _write(repo, {"dir": "now a file\n"})
    _git(repo, "checkout", "-q", current)
    if ignored:
        _ignored(repo, "dir/scratch")

    assert rounds._in_the_way(repo, current, target) == (["dir"] if ignored else [])


# A refused opening leaves the workspace's branch where it was.

@pytest.mark.parametrize("existing", [False, True], ids=["no branch", "branch at the base"])
def test_a_failed_checkout_puts_the_branch_back_and_opens_no_view(
        cloned: tuple[Path, Path, str, str], existing: bool) -> None:
    work, _, base, _ = cloned
    if existing:
        _git(work, "branch", BRANCH, base)
    # A held index lock fails the checkout; moving a ref takes no index lock.
    (work / ".git/index.lock").write_text("", "utf-8")

    with pytest.raises(rounds.RoundError, match="checkout"):
        _start(work)

    assert _git(work, "branch", "--list", BRANCH, "--format=%(objectname)") == (
        base if existing else "")
    assert (_git(work, "branch", "--show-current"), _git(work, "rev-parse", "HEAD")) == (
        "dev", base)
    assert rounds.open_view(work) is None
