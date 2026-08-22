"""Consumers of one hosted contract agree on which one, or the tree says so."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_hosted_client_pin",
    Path(__file__).resolve().parents[1] / "check-hosted-client-pin.py",
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tree(root: Path, *, source: str, followers: dict[Path, str]) -> Path:
    (root / checker.SOURCE.parent).mkdir(parents=True)
    (root / checker.SOURCE).write_text(
        f'dependencies = ["arkhai-hosted-settlement-client=={source}"]\n', "utf-8"
    )
    for path, version in followers.items():
        (root / path.parent).mkdir(parents=True, exist_ok=True)
        (root / path).write_text(
            f'dependencies = ["arkhai-hosted-settlement-client=={version}"]\n', "utf-8"
        )
    return root


def test_this_repository_agrees_with_itself() -> None:
    assert checker.main(["--root", str(REPO_ROOT)]) == 0


def test_a_follower_left_behind_is_named(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _tree(
        tmp_path,
        source="0.4.0",
        followers={checker.FOLLOWERS[0]: "0.4.0", checker.FOLLOWERS[1]: "0.3.0"},
    )

    assert checker.main(["--root", str(tmp_path)]) == 1

    error = capsys.readouterr().err
    assert str(checker.FOLLOWERS[1]) in error
    assert "0.3.0" in error and "0.4.0" in error
    # The file that agrees is not reported: a check that names innocent files
    # is one people stop reading.
    assert str(checker.FOLLOWERS[0]) not in error


def test_fix_moves_the_followers_to_the_named_version(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        source="0.4.0",
        followers={checker.FOLLOWERS[0]: "0.3.0", checker.FOLLOWERS[1]: "0.3.0"},
    )

    assert checker.main(["--root", str(tmp_path), "--fix"]) == 0
    assert checker.main(["--root", str(tmp_path)]) == 0
    for follower in checker.FOLLOWERS:
        assert "==0.4.0" in (tmp_path / follower).read_text("utf-8")


def test_a_file_stating_no_version_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path, source="0.4.0", followers={f: "0.4.0" for f in checker.FOLLOWERS})
    (tmp_path / checker.FOLLOWERS[0]).write_text("dependencies = []\n", "utf-8")

    assert checker.main(["--root", str(tmp_path)]) == 1
