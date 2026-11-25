"""The workflow's documents are found by role beside the engine: in an installed
package's data, or at the source tree's own places when the engine runs from it, and
the version is the installed metadata's or the tree's project file's."""

from __future__ import annotations

from pathlib import Path

import pytest

from change_workflow import documents
from change_workflow.documents import (COMPANION, DIAGRAMS, DISTRIBUTION, FRAGMENT, GUIDANCE,
                                       HANDBOOK, INDEX, ROLES, SCHEMA, SPECIFICATION,
                                       Distribution)

ROOT = Path(__file__).resolve().parents[2]
# Each role's file in a package's data, as the wheel's project file gathers it.
# The documents linking one another keep their tree paths, so their links resolve.
INSTALLED = {SPECIFICATION: "data/openspec/specs/change-workflow/spec.md",
             INDEX: "data/openspec/specs/change-workflow/index.md",
             COMPANION: "data/openspec/specs/change-workflow/README.md",
             DIAGRAMS: "data/openspec/specs/change-workflow/diagrams",
             GUIDANCE: "data/docs/guidance/workflow",
             HANDBOOK: "data/docs/change-workflow-handbook.md",
             SCHEMA: "data/change-outcome.schema.json",
             FRAGMENT: "workflow.mk"}
# The workflow's eleven skills.
SKILLS = ["change-archive-cleanup", "change-closeout", "change-design", "change-implement",
          "change-merge", "change-orchestrate", "change-plan", "change-review",
          "change-triage", "change-validate", "guidance-review"]


def _write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")


def _installed(tmp_path: Path) -> Path:
    package = tmp_path / "site-packages" / "change_workflow"
    _write(package / "__init__.py")
    for role, where in INSTALLED.items():
        _write(package / where / "x.md" if role in (DIAGRAMS, GUIDANCE) else package / where)
    for name in ("change-design", "guidance-review"):
        _write(package / "data/skills" / name / "SKILL.md")
    return package


def test_an_installed_package_finds_each_document_in_its_data(tmp_path: Path) -> None:
    package = _installed(tmp_path)
    distribution = Distribution(package, metadata_version={DISTRIBUTION: "0.4.2"}.__getitem__)

    assert distribution.installed
    assert distribution.documents() == {role: package / INSTALLED[role] for role in ROLES}
    assert distribution.skills() == {name: package / "data/skills" / name
                                     for name in ("change-design", "guidance-review")}
    assert distribution.version() == "0.4.2"


def test_the_source_tree_finds_each_document_where_the_tree_keeps_it(tmp_path: Path) -> None:
    package = tmp_path / "scripts" / "change_workflow"
    _write(package / "__init__.py")
    _write(tmp_path / "scripts/change-workflow-wheel/pyproject.toml",
           '[project]\nname = "arkhai-change-workflow"\nversion = "0.3.0"\n')
    for name in ("change-plan", "guidance-review", "openspec-propose", "change-empty"):
        _write(tmp_path / ".agents/skills" / name / ("SKILL.md" if name != "change-empty"
                                                     else "notes.md"))

    def unread(name: str) -> str:
        raise AssertionError(f"the tree's version is its project file's, not {name}'s metadata")

    distribution = Distribution(package, metadata_version=unread)

    assert not distribution.installed
    assert distribution.documents() == {
        SPECIFICATION: tmp_path / "openspec/specs/change-workflow/spec.md",
        INDEX: tmp_path / "openspec/specs/change-workflow/index.md",
        COMPANION: tmp_path / "openspec/specs/change-workflow/README.md",
        DIAGRAMS: tmp_path / "openspec/specs/change-workflow/diagrams",
        GUIDANCE: tmp_path / "docs/guidance/workflow",
        HANDBOOK: tmp_path / "docs/change-workflow-handbook.md",
        SCHEMA: tmp_path / ".agents/change-outcome.schema.json",
        FRAGMENT: package / "workflow.mk"}
    # The repository's own skills share the directory, and are not the workflow's.
    assert list(distribution.skills()) == ["change-plan", "guidance-review"]
    assert distribution.version() == "0.3.0"


def test_an_installed_distribution_is_its_package_and_its_metadata_on_disk(
        tmp_path: Path) -> None:
    package = _installed(tmp_path)
    metadata = package.parent / "arkhai_change_workflow-0.4.2.dist-info"
    metadata.mkdir()
    (package.parent / "other_tool-1.0.dist-info").mkdir()

    assert Distribution(package).installed_paths() == (package, metadata)


def test_the_source_tree_is_no_installed_distribution() -> None:
    assert documents.RUNNING.installed_paths() == ()


def test_a_role_the_distribution_does_not_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="'manual' is no document of the workflow's"):
        Distribution(_installed(tmp_path)).path("manual")


def test_the_engine_run_from_this_checkout_finds_every_document_of_its_tree() -> None:
    assert not documents.RUNNING.installed
    assert documents.RUNNING.tree == ROOT
    for role, path in documents.RUNNING.documents().items():
        assert path.exists(), role
        assert path.is_relative_to(ROOT), role
    assert list(documents.RUNNING.skills()) == SKILLS
    assert documents.version() == "0.1.0"
