"""A compacted session is told what to re-read and what is being worked."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "post_compaction_context", Path(__file__).resolve().parents[1] / "post_compaction_context.py"
)
assert _SPEC and _SPEC.loader
hook = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hook)

INDEX = """| Change | Status | Depends on | Notes |
|---|---|---|---|
| [`shape-bounds`](shape-bounds/) | in implementation | — | slice two next |
| [`old-thing`](archive/old-thing/) | archived | — | done |
| [`ci-job`](ci-job/) | ready for design | — | — |

| Order | Change | Status | Depends on | Notes |
|---|---|---|---|---|
| 1 | [`registry`](registry/) | in design | — | — |
"""


def test_only_changes_being_worked_are_listed() -> None:
    assert hook.changes_in_progress(INDEX) == [
        ("shape-bounds", "in implementation"), ("registry", "in design")]


def test_context_names_every_required_document_and_the_changes(tmp_path: Path) -> None:
    (tmp_path / "openspec/changes").mkdir(parents=True)
    (tmp_path / "openspec/changes/README.md").write_text(INDEX, "utf-8")

    text = hook.context(tmp_path)

    for path in hook.REQUIRED:
        assert f"- {path}" in text
    assert "- shape-bounds: in implementation" in text
    assert "Checked-out branch:" in text
    assert len(text) <= hook.LIMIT


def test_context_without_an_index_still_names_the_documents(tmp_path: Path) -> None:
    text = hook.context(tmp_path)

    assert "- docs/development/TESTING.md" in text
    assert "Changes in progress" not in text
