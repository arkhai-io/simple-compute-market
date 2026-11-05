"""The closing checks read only what a change's diff adds since it left the branch
it lands on, its uncommitted and untracked files included (real Git)."""

from __future__ import annotations

from pathlib import Path

import pytest

from change_diff import BaseNotFound, added_lines, file_at, merge_base
from change_diff_fixtures import change_repo, commit, git, write


def test_only_the_lines_the_branch_adds_are_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {"a.py": "one\ntwo\nthree\n"})
    commit(repo, {"a.py": "one\nTWO\nthree\nfour\n"})

    assert added_lines(repo, merge_base(repo), (".py",)) == {"a.py": {2, 4}}


def test_uncommitted_edits_and_untracked_files_are_the_changes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {"a.py": "one\n"})
    write(repo, "a.py", "one\ntwo\n")
    write(repo, "pkg/new.toml", "x = 1\ny = 2\n")
    write(repo, "notes.md", "not a suffix the check reads\n")

    assert added_lines(repo, merge_base(repo), (".py", ".toml")) == {
        "a.py": {2}, "pkg/new.toml": {1, 2}}


def test_a_commit_dev_gained_after_the_branch_left_it_is_not_the_changes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {"a.py": "one\n"})
    git(repo, "checkout", "-q", "dev")
    commit(repo, {"b.py": "landed on dev\n"})
    git(repo, "checkout", "-q", "feat/change")
    git(repo, "merge", "-q", "--no-edit", "dev")

    assert added_lines(repo, merge_base(repo), (".py",)) == {}


def test_the_branch_is_found_on_a_remote_when_it_is_not_local(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {"a.py": "one\n"})
    base = git(repo, "rev-parse", "dev")
    git(repo, "update-ref", "refs/remotes/workspace/dev", base)
    git(repo, "branch", "-q", "-D", "dev")

    assert merge_base(repo) == base
    assert file_at(repo, base, "a.py") == "one\n"
    assert file_at(repo, base, "missing.py") is None


def test_the_newest_copy_of_the_branch_is_read_when_another_lags(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {"a.py": "one\n"})
    stale = git(repo, "rev-parse", "dev")
    git(repo, "checkout", "-q", "dev")
    commit(repo, {"b.py": "landed on dev\n"})
    git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    git(repo, "branch", "-q", "-f", "feat/change", "HEAD")
    git(repo, "checkout", "-q", "feat/change")
    git(repo, "branch", "-q", "-f", "dev", stale)

    assert merge_base(repo) == git(repo, "rev-parse", "origin/dev")
    assert added_lines(repo, merge_base(repo), (".py",)) == {}


def test_an_added_line_starting_with_pluses_and_a_path_with_a_space_are_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {"a.py": "1\n2\n3\n4\n5\n",
                                               "my dir/b.py": "one\n"})
    # The `++ ` line prints as `+++ ` in the patch, before a.py's second hunk.
    commit(repo, {"a.py": "1\n++ two\n3\n4\nfive\n", "my dir/b.py": "one\ntwo\n"})

    assert added_lines(repo, merge_base(repo), (".py",)) == {
        "a.py": {2, 5}, "my dir/b.py": {2}}


def test_a_users_diff_prefixes_do_not_hide_the_added_lines(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {"a.py": "one\n"})
    write(repo, "a.py", "one\ntwo\n")
    git(repo, "config", "diff.mnemonicPrefix", "true")
    git(repo, "config", "diff.noprefix", "true")

    assert added_lines(repo, merge_base(repo), (".py",)) == {"a.py": {2}}


def test_a_branch_found_nowhere_is_refused_naming_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {})

    with pytest.raises(BaseNotFound, match="'release'"):
        merge_base(repo, "release")
