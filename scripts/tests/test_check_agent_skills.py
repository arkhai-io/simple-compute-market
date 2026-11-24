"""Every agent skill is loaded from its one source: the workflow's installed in each
harness's user skill directory, the repository's linked from `.agents/skills/`."""

from __future__ import annotations

import shutil
from pathlib import Path

from change_workflow import skills as checker
from change_workflow.documents import Distribution


def _repository(tmp_path: Path, *names: str) -> Path:
    root = tmp_path / "repo"
    for name in names:
        skill = root / ".agents/skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n", "utf-8")
        for harness in (".claude/skills", ".codex/skills"):
            (root / harness).mkdir(parents=True, exist_ok=True)
            (root / harness / name).symlink_to(Path("../../.agents/skills") / name)
    return root


def test_linked_skills_pass(tmp_path: Path) -> None:
    assert checker.problems(_repository(tmp_path, "review", "plan")) == []


def test_skill_missing_from_one_harness_fails(tmp_path: Path) -> None:
    root = _repository(tmp_path, "review")
    (root / ".codex/skills/review").unlink()

    assert checker.problems(root) == [".codex/skills/review: missing link to .agents/skills/review"]


def test_real_copy_in_a_harness_fails(tmp_path: Path) -> None:
    root = _repository(tmp_path, "review")
    (root / ".claude/skills/review").unlink()
    shutil.copytree(root / ".agents/skills/review", root / ".claude/skills/review")

    assert checker.problems(root) == [".claude/skills/review: a copy, not a link to .agents/skills/review"]


def test_harness_only_copy_fails(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / ".claude/skills/local").mkdir(parents=True)

    assert checker.problems(root) == [".claude/skills/local: a copy, not a link to .agents/skills/local"]


def test_dangling_link_fails(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / ".claude/skills").mkdir(parents=True)
    (root / ".claude/skills/gone").symlink_to("../../.agents/skills/gone")

    assert checker.problems(root) == [".claude/skills/gone: link does not resolve"]


def test_link_to_another_skill_fails(tmp_path: Path) -> None:
    root = _repository(tmp_path, "review", "plan")
    (root / ".codex/skills/review").unlink()
    (root / ".codex/skills/review").symlink_to("../../.agents/skills/plan")

    found = checker.problems(root)
    assert len(found) == 1
    assert found[0].startswith(".codex/skills/review: links to ")
    assert found[0].endswith("not .agents/skills/review")


def test_shared_skill_without_skill_file_fails(tmp_path: Path) -> None:
    root = _repository(tmp_path, "review")
    (root / ".agents/skills/review/SKILL.md").unlink()

    assert checker.problems(root) == [".agents/skills/review: shared skill has no SKILL.md"]


def test_the_workflows_own_sources_need_no_project_link(tmp_path: Path) -> None:
    """CW-d8de: the workflow's skills load from the user skill directories, so a
    source the tree keeps for the distribution asks no project link, while a skill the
    repository commits still does."""
    root = _repository(tmp_path, "change-plan", "openspec-propose", "change-design")
    for harness in (".claude/skills", ".codex/skills"):
        for name in ("change-plan", "change-design", "openspec-propose"):
            (root / harness / name).unlink()

    assert checker.problems(root, frozenset({"change-plan", "change-design"})) == [
        ".claude/skills/openspec-propose: missing link to .agents/skills/openspec-propose",
        ".codex/skills/openspec-propose: missing link to .agents/skills/openspec-propose"]


def test_a_project_entry_of_a_workflow_skills_name_fails(tmp_path: Path) -> None:
    """CW-d8de: a workflow skill has no project skill entry of its name, which would
    stand beside the installed skill as a second copy: refused, link or not."""
    root = _repository(tmp_path, "change-plan", "openspec-propose")
    (root / ".codex/skills/change-plan").unlink()
    (root / ".codex/skills/change-plan").mkdir()

    found = checker.problems(root, frozenset({"change-plan"}))

    assert found == [
        f"{harness}/change-plan: the workflow's skill change-plan is installed into the "
        "harness's user skill directory; no project entry of its name may stand beside it"
        for harness in (".claude/skills", ".codex/skills")]


def test_the_check_asks_no_link_of_the_running_distributions_skills(tmp_path: Path) -> None:
    # The installed half of the rule is held before every subcommand, this check's
    # among them (`test_change_workflow_install.py`); the check itself asks a link
    # only of a skill the running distribution does not ship.
    root = _repository(tmp_path, "openspec-propose", "change-plan")
    for harness in (".claude/skills", ".codex/skills"):
        (root / harness / "change-plan").unlink()
    tree = Distribution(Path(__file__).resolve().parents[1] / "change_workflow")

    assert checker.main(root, distribution=tree) == 0
