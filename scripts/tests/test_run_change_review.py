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


def _writing(text: str, status: int = 0, calls: list[list[str]] | None = None,
             session: str = "s-1"):
    def runner(command: Sequence[str], log: Path) -> int:
        if calls is not None:
            calls.append(list(command))
        log.write_text(f"--------\nsession id: {session}\n--------\nsession output\n", "utf-8")
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
    assert path.read_text("utf-8") == _review().rstrip("\n") + "\n\n<!-- reviewer-session: s-1 -->\n"
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


def test_a_later_review_continues_the_last_reviewer_read_only(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    reviewer.run_review(CHANGE, "design", root=root, runner=_writing(_review(), session="first"))
    calls: list[list[str]] = []

    path = reviewer.run_review(CHANGE, "design", root=root,
                               runner=_writing(_review(), calls=calls, session="first"))

    command = calls[0]
    assert command[:4] == ["codex", "exec", "resume", "first"]
    assert command[command.index("--config") + 1] == 'sandbox_mode="read-only"'
    assert "01-design" in command[-1] and "triage records" in command[-1]
    assert path.stem == "02-design"
    assert path.read_text("utf-8").endswith("<!-- reviewer-session: first -->\n")


def test_fresh_starts_a_new_reviewer(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    reviewer.run_review(CHANGE, "design", root=root, runner=_writing(_review(), session="first"))
    calls: list[list[str]] = []

    reviewer.run_review(CHANGE, "design", fresh=True, root=root,
                        runner=_writing(_review(), calls=calls, session="second"))

    assert calls[0][:3] == ["codex", "exec", "--sandbox"]


def test_a_review_of_another_kind_does_not_continue(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    reviewer.run_review(CHANGE, "design", root=root, runner=_writing(_review(), session="first"))
    calls: list[list[str]] = []

    reviewer.run_review(CHANGE, "implementation", root=root,
                        runner=_writing(_review("implementation"), calls=calls))

    assert "resume" not in calls[0]


def test_an_external_review_is_never_continued(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (_reviews(root) / "01-design-external.md").write_text(_review(), "utf-8")
    calls: list[list[str]] = []

    reviewer.run_review(CHANGE, "design", root=root, runner=_writing(_review(), calls=calls))

    assert "resume" not in calls[0]
