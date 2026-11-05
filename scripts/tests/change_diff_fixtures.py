"""A temporary Git repository with a `dev` branch and a change's branch off it, for
the closing checks that read what a change's diff adds."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_IDENTITY = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
             "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
             "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def write(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def commit(repo: Path, files: dict[str, str], message: str = "edit") -> None:
    for name, text in files.items():
        write(repo, name, text)
        git(repo, "add", name)
    git(repo, "commit", "-qm", message)


def change_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                base_files: dict[str, str]) -> Path:
    """A repository whose `dev` holds `base_files`, checked out on a change's branch."""
    for key, value in _IDENTITY.items():
        monkeypatch.setenv(key, value)
    git(tmp_path, "init", "-q", "-b", "dev")
    git(tmp_path, "commit", "--allow-empty", "-qm", "root")
    if base_files:
        commit(tmp_path, base_files, "base")
    git(tmp_path, "checkout", "-q", "-b", "feat/change")
    return tmp_path
