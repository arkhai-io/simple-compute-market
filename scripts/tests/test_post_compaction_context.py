"""A compacted session is told what to re-read and what is being worked."""

from __future__ import annotations

from pathlib import Path

from change_workflow import config, hook
from change_workflow_fixtures import configured

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


LOAD = '[load]\ncommon = ["GUIDE.md", "docs/TESTS.md"]\ndesign = ["docs/ROADMAP.md"]\n'


def test_context_names_the_configured_common_documents_and_the_changes(tmp_path: Path) -> None:
    """CW-l7hn: the hook has the session re-read `load.common`, not knowing its
    step, so a step's own additions are not named."""
    configured(tmp_path, LOAD)
    (tmp_path / "openspec/changes").mkdir(parents=True)
    (tmp_path / "openspec/changes/README.md").write_text(INDEX, "utf-8")

    text = hook.context(tmp_path)

    assert "- GUIDE.md\n- docs/TESTS.md\n" in text
    assert "ROADMAP" not in text
    assert "- shape-bounds: in implementation" in text
    assert "Checked-out branch:" in text
    assert len(text) <= hook.LIMIT


def test_context_without_an_index_still_names_the_documents(tmp_path: Path) -> None:
    configured(tmp_path, LOAD)

    text = hook.context(tmp_path)

    assert "- docs/TESTS.md" in text
    assert "Changes in progress" not in text


def test_context_with_no_common_documents_says_so(tmp_path: Path) -> None:
    text = hook.context(tmp_path)

    assert "lists no documents every step reads" in text
    assert "\n- " not in text.split("Checked-out branch")[0]


def test_a_malformed_configuration_is_named_and_the_session_still_told(tmp_path: Path) -> None:
    configured(tmp_path, "[load]\ncommons = []\n")

    text = hook.context(tmp_path)

    assert "load.commons is no field" in text
    assert "Re-read the repository's guidance" in text


def test_this_repositorys_hook_names_its_configured_documents() -> None:
    repository = Path(__file__).resolve().parents[2]

    text = hook.context(repository)

    for document in config.load(repository).documents("common"):
        assert f"- {document}\n" in text
