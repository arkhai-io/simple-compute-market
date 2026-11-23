"""A compacted session is told what to re-read and what is being worked."""

from __future__ import annotations

from pathlib import Path

from change_workflow import config, hook
from change_workflow import documents as distribution
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


def test_context_names_the_engineering_and_workflow_guidance_before_the_common_documents(
        tmp_path: Path) -> None:
    """CW-l7hn: the hook names what `config load common` prints: the Markdown files
    beneath the engineering pointer, the workflow's guidance, then `load.common`."""
    configured(tmp_path, LOAD)
    (tmp_path / "guides/engineering").mkdir(parents=True)
    (tmp_path / "guides/engineering/tests.md").write_text("# Tests\n", "utf-8")
    (tmp_path / config.LOCAL).write_text(
        '[guidance]\nengineering = { path = "guides/engineering/" }\n', "utf-8")

    text = hook.context(tmp_path)

    named = [line[2:] for line in text.split("Checked-out branch")[0].splitlines()
             if line.startswith("- ")]
    workflow = sorted(path for path in distribution.path(distribution.GUIDANCE).rglob("*.md"))
    assert named == ["guides/engineering/tests.md", *map(str, workflow), "GUIDE.md",
                     "docs/TESTS.md"]


def test_context_with_no_local_configuration_names_the_installer(tmp_path: Path) -> None:
    """With no pointer the documents to re-read are unknown: the session is told what
    is missing and how to write it, and still told to re-read its guidance."""
    text = hook.context(tmp_path)

    assert "guidance.engineering" in text and "`change-workflow install`" in text
    assert "Re-read the repository's guidance" in text


def test_context_with_a_pointer_applying_none_names_the_workflows_guidance(
        tmp_path: Path) -> None:
    configured(tmp_path, "")

    text = hook.context(tmp_path)

    assert f"- {distribution.path(distribution.GUIDANCE) / 'README.md'}\n" in text


def test_a_malformed_configuration_is_named_and_the_session_still_told(tmp_path: Path) -> None:
    configured(tmp_path, "[load]\ncommons = []\n")

    text = hook.context(tmp_path)

    assert "load.commons is no field" in text
    assert "Re-read the repository's guidance" in text


def test_this_repositorys_hook_names_its_configured_documents() -> None:
    repository = Path(__file__).resolve().parents[2]

    text = hook.context(repository)

    for document in config.load(repository).documents("common", repository):
        assert f"- {document}\n" in text


def test_a_directory_entry_is_named_as_the_files_beneath_it(tmp_path: Path) -> None:
    """CW-l7hn's scenario "A directory entry": the hook names each file, not the
    directory."""
    configured(tmp_path, '[load]\ncommon = ["AGENTS.md", "docs/guidance/"]\n')
    for path in ("docs/guidance/workflow/closeout.md", "docs/guidance/engineering/comments.md"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("# x\n", "utf-8")

    text = hook.context(tmp_path)

    assert ("- AGENTS.md\n- docs/guidance/engineering/comments.md\n"
            "- docs/guidance/workflow/closeout.md\n") in text
    assert "- docs/guidance/\n" not in text


def test_a_directory_entry_naming_nothing_leaves_the_documents_unknown(tmp_path: Path) -> None:
    """CW-l7hn's scenario "A directory entry names nothing": the session is told the
    documents to re-read are unknown, naming the entry, and no list is given."""
    configured(tmp_path, '[load]\ncommon = ["AGENTS.md", "docs/guidens/"]\n')

    text = hook.context(tmp_path)

    assert "The documents to re-read are unknown" in text
    assert "docs/guidens/" in text
    assert "- AGENTS.md" not in text
    assert "Re-read the repository's guidance" in text
