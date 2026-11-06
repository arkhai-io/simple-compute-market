"""The review snapshot preserves symlinks, so shared agent skills survive it."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _snapshot_zip_flags() -> list[str]:
    recipe = (ROOT / "Makefile").read_text("utf-8").split("\ncode-snapshot:", 1)[1]
    match = re.search(r"\| zip ((?:-\S+ )+)", recipe)
    assert match, "code-snapshot no longer pipes tracked paths into zip"
    return match.group(1).split()


@pytest.mark.skipif(not (shutil.which("zip") and shutil.which("unzip")), reason="needs zip and unzip")
def test_a_linked_skill_round_trips_as_a_link(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    (tree / ".agents/skills/review").mkdir(parents=True)
    (tree / ".agents/skills/review/SKILL.md").write_text("---\nname: review\n---\n", "utf-8")
    (tree / ".claude/skills").mkdir(parents=True)
    (tree / ".claude/skills/review").symlink_to("../../.agents/skills/review")
    archive = tmp_path / "snapshot.zip"

    subprocess.run(["zip", "-q", *_snapshot_zip_flags(), str(archive)], cwd=tree, check=True,
                   input=".agents/skills/review/SKILL.md\n.claude/skills/review\n", text=True)
    subprocess.run(["unzip", "-q", str(archive), "-d", str(tmp_path / "out")], check=True)

    link = tmp_path / "out/.claude/skills/review"
    assert link.is_symlink()
    assert (link / "SKILL.md").is_file()
