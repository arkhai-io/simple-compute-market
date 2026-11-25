"""A change's untracked review records are not checked for citations."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from workflow_stand_in import change as found_as, put_on_path

ACTIVE = found_as("shape-bounds", "openspec/changes/shape-bounds")
ARCHIVED = found_as("shape-bounds", "openspec/changes/archive/2026-10-14-shape-bounds",
                  archived=True)

_SPEC = importlib.util.spec_from_file_location(
    "check_doc_citations", Path(__file__).resolve().parents[1] / "check_doc_citations.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


def _workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, found=ACTIVE,
              created: tuple[str, ...] = ()) -> None:
    """The workflow's command, a stand-in outside the test's root, answering that the
    change is `found`, and that its deltas create `created`."""
    put_on_path(monkeypatch, tmp_path.parent / f"{tmp_path.name}-workflow", found, created)


@pytest.fixture(autouse=True)
def _active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _workflow(tmp_path, monkeypatch)


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


def test_a_change_is_found_by_name_once_archived(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    _workflow(tmp_path, monkeypatch, ARCHIVED)
    change = _change(tmp_path)
    archived = tmp_path / "openspec/changes/archive/2026-10-14-shape-bounds"
    archived.parent.mkdir()
    change.rename(archived)

    found = checker.documents(tmp_path, "shape-bounds")

    assert [path.relative_to(archived).as_posix() for path in found] == [
        "specs/kit/spec.md", "why.md"]


def test_an_unknown_change_is_refused(tmp_path: Path) -> None:
    _change(tmp_path)

    with pytest.raises(SystemExit, match="no change 'other'"):
        checker.documents(tmp_path, "other")


def test_an_archived_change_citing_its_own_unarchived_path_resolves(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _workflow(tmp_path, monkeypatch, ARCHIVED)
    archived = tmp_path / "openspec/changes/archive/2026-10-14-shape-bounds"
    archived.mkdir(parents=True)
    (archived / "notes.md").write_text("x", "utf-8")
    (archived / "why.md").write_text(
        "see openspec/changes/shape-bounds/notes.md and openspec/changes/shape-bounds/gone.md,"
        " and docs/missing.md\n",
        "utf-8")

    problems = checker.unresolvable(tmp_path, "shape-bounds")

    assert sorted(cited for _, cited, _ in problems) == [
        "docs/missing.md", "openspec/changes/shape-bounds/gone.md"]


def test_a_cited_agents_path_must_resolve(tmp_path: Path) -> None:
    change = tmp_path / "openspec/changes/shape-bounds"
    change.mkdir(parents=True)
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/change-outcome.schema.json").write_text("{}", "utf-8")
    (change / "why.md").write_text(
        "matches `.agents/change-outcome.schema.json`, not `.agents/gone.json`; "
        "a `.claude/skills/x.md` mirror is not checked\n", "utf-8")

    assert [cited for _, cited, _ in checker.unresolvable(tmp_path, "shape-bounds")] == [
        ".agents/gone.json"]


def test_a_checkouts_local_configuration_need_not_exist(tmp_path: Path) -> None:
    # A checkout's local configuration is on no branch, so a citation of it does
    # not resolve to a file, while any other absent path still fails, ignored or not.
    change = tmp_path / "openspec/changes/shape-bounds"
    change.mkdir(parents=True)
    (tmp_path / ".gitignore").write_text("*.local.toml\n", "utf-8")
    (change / "why.md").write_text(
        "`.agents/workflow.local.toml`, written from `.agents/workflow.local.template.toml`, "
        "not `.agents/other.local.toml`\n", "utf-8")

    assert [cited for _, cited, _ in checker.unresolvable(tmp_path, "shape-bounds")] == [
        ".agents/other.local.toml", ".agents/workflow.local.template.toml"]


def test_a_citation_check_meets_a_specification_the_change_creates(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The workflow's `check spec-index --json` lists the specification the change's
    delta creates, and the citation check, reading it through the command, accepts
    the citation; what a delta creates is the workflow's to compute."""
    _workflow(tmp_path, monkeypatch, created=("openspec/specs/new-flow/spec.md",))
    change = tmp_path / "openspec/changes/shape-bounds"
    change.mkdir(parents=True)
    (change / "why.md").write_text(
        "writes openspec/specs/new-flow/spec.md, not openspec/specs/new-flow/README.md"
        " or openspec/specs/other-flow/spec.md\n",
        "utf-8")

    assert [cited for _, cited, _ in checker.unresolvable(tmp_path, "shape-bounds")] == [
        "openspec/specs/new-flow/README.md", "openspec/specs/other-flow/spec.md"]
    # The repository-wide view holds every document, permanent ones among them, to
    # what exists.
    assert "openspec/specs/new-flow/spec.md" in [
        cited for _, cited, _ in checker.unresolvable(tmp_path)]


def test_an_active_change_citing_its_own_path_must_resolve_as_written(tmp_path: Path) -> None:
    change = tmp_path / "openspec/changes/shape-bounds"
    change.mkdir(parents=True)
    (change / "why.md").write_text("see openspec/changes/shape-bounds/gone.md\n", "utf-8")

    assert [cited for _, cited, _ in checker.unresolvable(tmp_path, "shape-bounds")] == [
        "openspec/changes/shape-bounds/gone.md"]
