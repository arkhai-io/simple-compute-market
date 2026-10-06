"""A change review is run read-only and recorded as the change's next review."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Sequence

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_change_review", Path(__file__).resolve().parents[1] / "run_change_review.py"
)
assert _SPEC and _SPEC.loader
reviewer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(reviewer)


def _repository(tmp_path: Path, *records: str) -> Path:
    change = tmp_path / "openspec/changes/shape-bounds"
    change.mkdir(parents=True)
    if records:
        (change / "reviews").mkdir()
        for name in records:
            (change / "reviews" / name).write_text("x", "utf-8")
    return tmp_path


def _writing(text: str, status: int = 0, calls: list[list[str]] | None = None):
    def runner(command: Sequence[str], log: Path) -> int:
        if calls is not None:
            calls.append(list(command))
        log.write_text("session output\n", "utf-8")
        Path(command[command.index("--output-last-message") + 1]).write_text(text, "utf-8")
        return status
    return runner


def test_first_review_is_numbered_one(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    kind = "design"
    path = reviewer.run_review("shape-bounds", kind, root=root, runner=_writing("# Design review"))

    assert path == root / "openspec/changes/shape-bounds/reviews" / f"01-{kind}.md"
    assert path.read_text("utf-8") == "# Design review"
    assert path.with_suffix(".log").is_file()


def test_review_follows_every_existing_record(tmp_path: Path) -> None:
    root = _repository(tmp_path, "01-design.log", "01-design.triage.log", "02-validation.log")

    path = reviewer.run_review("shape-bounds", "implementation", root=root, runner=_writing("# Review"))

    assert path.name == "03-implementation.md"


def test_reviewer_runs_read_only_with_the_skill(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    reviewer.run_review("shape-bounds", "pre-closeout", base="main", model="m1", root=root,
                        runner=_writing("# Review", calls=calls))

    command = calls[0]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "m1"
    assert command[-1] == ("Use the change-review skill. Review kind: pre-closeout. "
                           "Change: shape-bounds. Base: main.")


def test_design_review_names_no_base(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    reviewer.run_review("shape-bounds", "design", root=root, runner=_writing("# Review", calls=calls))

    assert "Base:" not in calls[0][-1]
    assert "--model" not in calls[0]


@pytest.mark.parametrize("text,status", [("", 0), ("   \n", 0), ("# Review", 1)])
def test_failed_or_empty_review_leaves_no_record(tmp_path: Path, text: str, status: int) -> None:
    root = _repository(tmp_path)

    with pytest.raises(reviewer.ReviewError, match="produced no review"):
        reviewer.run_review("shape-bounds", "design", root=root, runner=_writing(text, status))

    reviews = root / "openspec/changes/shape-bounds/reviews"
    assert not (reviews / "01-design.log").with_suffix(".md").exists()
    assert (reviews / "01-design.log").is_file()


@pytest.mark.parametrize("change,kind", [("missing", "design"), ("archive", "design"), ("../x", "design"),
                                         ("shape-bounds", "triage")])
def test_unknown_change_or_kind_is_refused(tmp_path: Path, change: str, kind: str) -> None:
    root = _repository(tmp_path)

    with pytest.raises(reviewer.ReviewError):
        reviewer.run_review(change, kind, root=root, runner=_writing("# Review"))
