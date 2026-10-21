"""Every agent skill is loaded from its one shared source."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_agent_skills", Path(__file__).resolve().parents[1] / "check_agent_skills.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


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
