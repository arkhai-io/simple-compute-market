"""A change review is run read-only and published only when it is a review."""

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

CHANGE = "shape-bounds"
FINDING = """### F1 — The override has no carrier

- **Lens:** architecture
- **Basis:** evidence
- **Severity:** blocking
- **Evidence:** `kit/pool-overrides/records.py:43`

The record has no field for it.

**Suggested action:** Choose one.
"""


def _review(kind: str = "design", findings: str = FINDING) -> str:
    return (f"# {kind.capitalize()} review — {CHANGE}\n\n## Summary\n\nWhat it does.\n\n"
            "## Assessment\n\nSound.\n\n## Questions\n\n### consistency — Is it consistent?\n\n"
            f"Yes.\n\n## Findings\n\n{findings}\n## Readiness\n\nNot yet.\n")


def _repository(tmp_path: Path, *records: str) -> Path:
    reviews = tmp_path / "openspec/changes" / CHANGE / "reviews"
    reviews.mkdir(parents=True)
    for name in records:
        (reviews / name).parent.mkdir(parents=True, exist_ok=True)
        (reviews / name).write_text("x", "utf-8")
    return tmp_path


def _writing(text: str, status: int = 0, calls: list[list[str]] | None = None):
    def runner(command: Sequence[str], log: Path) -> int:
        if calls is not None:
            calls.append(list(command))
        log.write_text("session output\n", "utf-8")
        Path(command[command.index("--output-last-message") + 1]).write_text(text, "utf-8")
        return status
    return runner


def _reviews(root: Path) -> Path:
    return root / "openspec/changes" / CHANGE / "reviews"


def test_a_review_is_published_and_its_transcript_kept_apart(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    kind = "design"

    path = reviewer.run_review(CHANGE, kind, root=root, runner=_writing(_review()))

    assert path == _reviews(root) / f"01-{kind}.md"
    assert path.read_text("utf-8") == _review()
    assert (_reviews(root) / "transcripts" / "01-design.log").is_file()
    assert sorted(p.name for p in _reviews(root).iterdir()) == [path.name, "transcripts"]


def test_numbering_follows_records_and_transcripts(tmp_path: Path) -> None:
    root = _repository(tmp_path, "01-design.log", "02-validation.log", "transcripts/03-implementation.log")

    path = reviewer.run_review(CHANGE, "implementation", root=root,
                               runner=_writing(_review("implementation")))

    assert path.name == "04-implementation.md"


def test_reviewer_runs_read_only_with_the_skill(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    reviewer.run_review(CHANGE, "pre-closeout", base="main", model="m1", effort="high", root=root,
                        runner=_writing(_review("pre-closeout"), calls=calls))

    command = calls[0]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "m1"
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="high"'
    assert command[-1] == ("Use the change-review skill. Review kind: pre-closeout. "
                           f"Change: {CHANGE}. Base: main.")


def test_design_review_names_no_base(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    reviewer.run_review(CHANGE, "design", root=root, runner=_writing(_review(), calls=calls))

    assert "Base:" not in calls[0][-1]
    assert "--model" not in calls[0]
    assert "--config" not in calls[0]


def test_a_review_with_no_findings_is_accepted(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    path = reviewer.run_review(CHANGE, "design", root=root,
                               runner=_writing(_review(findings="None: the change needs none.\n")))

    assert path.is_file()


@pytest.mark.parametrize("text,status,reason", [
    ("", 0, "empty"),
    (_review(), 1, "exited 1"),
    ("ERROR: the model is not supported\n", 0, "title"),
    (_review().replace("## Questions", "## Notes"), 0, "missing section '## Questions'"),
    (_review().replace("- **Basis:** evidence\n", ""), 0, "F1 has no Basis"),
    (_review().replace("blocking", "urgent"), 0, "F1 has Severity 'urgent'"),
    (_review("implementation"), 0, "title"),
])
def test_output_that_is_not_a_review_publishes_nothing(
    tmp_path: Path, text: str, status: int, reason: str
) -> None:
    root = _repository(tmp_path)

    with pytest.raises(reviewer.ReviewError, match=reason):
        reviewer.run_review(CHANGE, "design", root=root, runner=_writing(text, status))

    assert [p.name for p in _reviews(root).iterdir()] == ["transcripts"]
    assert (_reviews(root) / "transcripts" / "01-design.log").is_file()


def test_rejected_output_is_kept_with_its_transcript(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    with pytest.raises(reviewer.ReviewError):
        reviewer.run_review(CHANGE, "design", root=root, runner=_writing("ERROR: refused\n"))

    rejected = _reviews(root) / "transcripts" / "01-design.rejected.md"
    assert rejected.read_text("utf-8") == "ERROR: refused\n"


@pytest.mark.parametrize("change,kind", [("missing", "design"), ("archive", "design"), ("../x", "design"),
                                         (CHANGE, "triage")])
def test_unknown_change_or_kind_is_refused(tmp_path: Path, change: str, kind: str) -> None:
    root = _repository(tmp_path)

    with pytest.raises(reviewer.ReviewError):
        reviewer.run_review(change, kind, root=root, runner=_writing(_review()))
