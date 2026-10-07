"""A change's untracked review records are not checked for citations."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_doc_citations", Path(__file__).resolve().parents[1] / "check_doc_citations.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


def _change(root: Path) -> Path:
    change = root / "openspec/changes/shape-bounds"
    (change / "reviews/transcripts").mkdir(parents=True)
    (change / "specs/kit").mkdir(parents=True)
    for name in ("why", "specs/kit/spec", "reviews/03-review", "reviews/transcripts/03-note"):
        (change / f"{name}.md").write_text("cites openspec/changes/gone.md\n", "utf-8")
    return change


def test_review_records_are_not_documents_of_a_change(tmp_path: Path) -> None:
    change = _change(tmp_path)

    found = checker.documents(tmp_path, "shape-bounds")

    assert [path.relative_to(change).as_posix() for path in found] == [
        "specs/kit/spec.md", "why.md"]


def test_repository_view_also_skips_review_records(tmp_path: Path) -> None:
    _change(tmp_path)

    found = checker.documents(tmp_path)

    assert not any("reviews" in path.parts for path in found)
    assert len(found) == 2
