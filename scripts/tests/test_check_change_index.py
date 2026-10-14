"""The change index is checked against the change directories it lists."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_change_index", Path(__file__).resolve().parents[1] / "check_change_index.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

HEADER = "| Change | Status | Depends on | Notes | Acceptance boundary |\n|---|---|---|---|---|\n"


def _row(name: str, status: str = "ready for design", depends: str = "—",
         path: str | None = None) -> str:
    return f"| [`{name}`]({path or name + '/'}) | {status} | {depends} | — | Scope |\n"


def _index(root: Path, *rows: str, directories: tuple[str, ...] = (), extra: str = "") -> Path:
    changes = root / "openspec/changes"
    for directory in directories:
        (changes / directory).mkdir(parents=True)
    changes.mkdir(parents=True, exist_ok=True)
    (changes / "README.md").write_text("# Changes\n\n" + HEADER + "".join(rows) + extra, "utf-8")
    return root


def _problems(root: Path) -> list[str]:
    return checker.check(root)


def test_a_consistent_index_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _index(
        tmp_path,
        _row("alpha", depends="`beta` (design)"),
        _row("beta", status="in implementation"),
        _row("gamma", status="archived", path="archive/2026-01-02-gamma/"),
        directories=("alpha", "beta", "archive/2026-01-02-gamma"),
    )

    assert checker.main(root) == 0
    assert "OK" in capsys.readouterr().out


def test_a_row_with_the_wrong_cell_count_is_reported(tmp_path: Path) -> None:
    root = _index(tmp_path, "| [`alpha`](alpha/) | ready for design | — |\n",
                  directories=("alpha",))

    (problem,) = [p for p in _problems(root) if "cells" in p]
    assert "3 cells under a header of 5" in problem


def test_an_unknown_status_is_reported(tmp_path: Path) -> None:
    root = _index(tmp_path, _row("alpha", status="planned"), directories=("alpha",))

    assert any("'planned' is not in the legend" in p for p in _problems(root))


@pytest.mark.parametrize(("path", "message"), [
    ("alpah/", "not its own directory"),
    ("archive/2026-01-02-beta/", "another change's archive"),
])
def test_a_link_to_the_wrong_directory_is_reported(tmp_path: Path, path: str, message: str) -> None:
    root = _index(tmp_path, _row("alpha", path=path), directories=("alpha",))

    assert any(message in p for p in _problems(root))


def test_a_link_to_a_missing_directory_is_reported(tmp_path: Path) -> None:
    root = _index(tmp_path, _row("alpha"), _row("beta"), directories=("alpha",))

    assert any("beta: links 'beta/', which does not exist" in p for p in _problems(root))


@pytest.mark.parametrize(("status", "path", "message"), [
    ("archived", "alpha/", "archived but links"),
    ("in implementation", "archive/2026-01-02-alpha/", "links its archive but is"),
])
def test_status_and_link_must_agree_on_archival(
        tmp_path: Path, status: str, path: str, message: str) -> None:
    root = _index(tmp_path, _row("alpha", status=status, path=path),
                  directories=("alpha", "archive/2026-01-02-alpha"))

    assert any(message in p for p in _problems(root))


def test_a_change_in_closeout_may_link_its_archive(tmp_path: Path) -> None:
    root = _index(tmp_path, _row("alpha", status="in closeout", path="archive/2026-01-02-alpha/"),
                  directories=("archive/2026-01-02-alpha",))

    assert _problems(root) == []


def test_a_dependency_on_an_archived_change_is_reported(tmp_path: Path) -> None:
    root = _index(
        tmp_path,
        _row("alpha", depends="`gamma`"),
        _row("gamma", status="archived", path="archive/2026-01-02-gamma/"),
        directories=("alpha", "archive/2026-01-02-gamma"),
    )

    assert any("archive cleanup releases it" in p for p in _problems(root))


@pytest.mark.parametrize(("depends", "message"), [
    ("`missing`", "lists no such change"),
    ("`beta` (review)", "'review' is not a phase"),
    ("beta", "not a change name"),
])
def test_a_malformed_or_unknown_dependency_is_reported(
        tmp_path: Path, depends: str, message: str) -> None:
    root = _index(tmp_path, _row("alpha", depends=depends), _row("beta"),
                  directories=("alpha", "beta"))

    assert any(message in p for p in _problems(root))


def test_a_change_directory_without_a_row_is_reported(tmp_path: Path) -> None:
    root = _index(tmp_path, _row("alpha"), directories=("alpha", "beta"))

    assert _problems(root) == ["openspec/changes/README.md: no row for openspec/changes/beta/"]


def test_a_table_without_a_status_column_is_checked_only_for_its_shape(tmp_path: Path) -> None:
    extra = "\n| Item | Origin |\n|---|---|\n| A finding | `alpha` |\n| Short |\n"
    root = _index(tmp_path, _row("alpha"), directories=("alpha",), extra=extra)

    (problem,) = _problems(root)
    assert "1 cells under a header of 2" in problem


def test_make_target_runs_the_checker() -> None:
    command = subprocess.run(
        ["make", "-n", "--no-print-directory", "check-change-index"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=True,
    ).stdout

    assert "scripts/check_change_index.py" in command
