"""The distribution's skills cite the workflow's own guidance only by sections it
heads: a skill citing a section the shipped guidance lost fails here, naming the
skill and the section (CW-lm42).

Unit tests over the distribution's document set, as `documents` finds it: the tree's
when run from it, the package's when installed."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from change_workflow import documents, sections


def unresolved_citations(skills: Mapping[str, str], guidance: Path) -> list[str]:
    """Each workflow-guidance section a skill, by name and text, cites that no file of
    `guidance` heads, or several do, naming the skill."""
    found = sections.heads(guidance)
    citing = sections.citing(skills, sections.WORKFLOW)
    return [f'{skill} cites the workflow guidance\'s section "{name}", which '
            + (f"heads a section in each of {', '.join(map(str, files))}" if files
               else "no file of the shipped guidance heads")
            for name, files in sections.unresolved(citing, found).items()
            for skill in sorted(citing[name])]


def _skills(distribution: documents.Distribution) -> dict[str, str]:
    return {name: (source / "SKILL.md").read_text("utf-8")
            for name, source in distribution.skills().items()}


def test_every_workflow_section_a_skill_cites_is_shipped() -> None:
    shipped = documents.RUNNING
    skills = _skills(shipped)

    assert sections.citing(skills, sections.WORKFLOW), "no skill cites the workflow's guidance"
    assert unresolved_citations(skills, shipped.path(documents.GUIDANCE)) == []


def test_a_skill_cites_a_section_the_guidance_lost(tmp_path: Path) -> None:
    """CW-lm42's "A skill cites a section the guidance lost": the heading renamed, the
    test fails, naming the skill and the section."""
    (tmp_path / "changes.md").write_text("# A change's documents\n\n## One change a branch\n",
                                         "utf-8")
    skills = {"change-plan": 'as the workflow guidance\'s section "One change per branch" says'}

    assert unresolved_citations(skills, tmp_path) == [
        'change-plan cites the workflow guidance\'s section "One change per branch", which no '
        "file of the shipped guidance heads"]
