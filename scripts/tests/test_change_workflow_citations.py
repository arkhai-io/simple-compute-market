"""The distribution's skills cite the workflow's own guidance only by sections it
heads: a skill citing a section the shipped guidance lost fails here, naming the
skill and the section, as does one citing a requirement id its specification does
not hold (CW-lm42). The distribution's documents link only within their own set, so
the set is lifted whole and reads whole wherever it is kept.

Unit tests over the distribution's document set, as `documents` finds it: the tree's
when run from it, the package's when installed. A relative link is written for the
tree's layout, which a lift keeps, so the links are read in the tree alone."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

import pytest

from change_workflow import documents, sections

# A Markdown link or image, its target up to the first space or closing parenthesis.
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)")
_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)", re.S)
_FENCE = re.compile(r"^\s*(```|~~~)")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:")
# A requirement id of the workflow's specification, and the heading that defines one.
_ID = re.compile(r"(?<![\w-])CW-[a-z0-9]{4}(?![\w-])")
_REQUIREMENT = re.compile(r"^### Requirement: (CW-[a-z0-9]{4})\b", re.M)


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


def _roots(distribution: documents.Distribution) -> list[Path]:
    """Each document the distribution ships by role, and each skill's directory."""
    return [*distribution.documents().values(), *distribution.skills().values()]


def document_set(distribution: documents.Distribution) -> set[Path]:
    """Every file the distribution ships as a document, a skill among them, resolved."""
    return {path.resolve() for root in _roots(distribution)
            for path in ([root] if root.is_file() else root.rglob("*")) if path.is_file()}


def _prose(markdown: str) -> str:
    """`markdown` with its fenced blocks and code spans blanked, line numbers kept:
    a link written as code is an example, not a link."""
    lines, fenced = [], False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            lines.append("")
            continue
        lines.append("" if fenced else line)
    return _SPAN.sub(lambda match: re.sub(r"[^\n]", " ", match[0]), "\n".join(lines))


def links_leaving(distribution: documents.Distribution) -> list[str]:
    """Each relative link of a Markdown document of the set whose file is no file or
    directory of the set, as `<document>:<line>: <target>`."""
    shipped = document_set(distribution)
    directories = {path.resolve() for root in _roots(distribution) if root.is_dir()
                   for path in (root, *root.rglob("*")) if path.is_dir()}
    found = []
    for document in sorted(path for path in shipped if path.suffix == ".md"):
        text = _prose(document.read_text("utf-8"))
        for match in _LINK.finditer(text):
            target = match[1].split("#", 1)[0]
            if not target or _SCHEME.match(target):
                continue
            resolved = (document.parent / target).resolve()
            if resolved not in shipped and resolved not in directories:
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{document.relative_to(distribution.tree)}:{line}: {match[1]}")
    return found


def test_the_workflows_documents_link_only_within_their_set() -> None:
    if documents.RUNNING.installed:
        pytest.skip("relative links are written for the tree's layout")
    assert document_set(documents.RUNNING), "the distribution ships no document"

    assert links_leaving(documents.RUNNING) == []


def test_a_link_leaving_the_set_is_named(tmp_path: Path) -> None:
    """A workflow document linking a repository's own document fails, naming the
    document, the line, and the link; a link within the set, to a heading, an
    external link, and a link written as code are none."""
    package = tmp_path / "scripts/change_workflow"
    package.mkdir(parents=True)
    tree = documents.Distribution(package)
    for role, path in tree.documents().items():
        if role in (documents.DIAGRAMS, documents.GUIDANCE):
            path.mkdir(parents=True, exist_ok=True)
            (path / ("a.svg" if role == documents.DIAGRAMS else "a.md")).write_text("x")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# A document\n", "utf-8")
    tree.path(documents.COMPANION).write_text(
        "# Companion\n\nSee [the spec](spec.md#a), ![a](diagrams/a.svg), "
        "[the guide](../../../docs/guidance/workflow/a.md), [x](https://example.org),\n"
        "`[not a link](../elsewhere.md)`, [a heading](#a), [this repository's](../other/README.md), "
        "and [its tree](../../).\n\n```markdown\n[an example](../example.md)\n```\n", "utf-8")

    assert links_leaving(tree) == [
        "openspec/specs/change-workflow/README.md:4: ../other/README.md",
        "openspec/specs/change-workflow/README.md:4: ../../"]


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


def unheld_ids(texts: Mapping[str, str], specification: str) -> list[str]:
    """Each requirement id a text, by name, cites that no requirement of
    `specification` carries, naming the text."""
    held = set(_REQUIREMENT.findall(specification))
    return [f"{name} cites {cited}, which the shipped specification does not hold"
            for name, text in sorted(texts.items())
            for cited in sorted(set(_ID.findall(text)) - held)]


def test_every_requirement_id_a_skill_or_the_guidance_cites_is_shipped() -> None:
    shipped = documents.RUNNING
    guidance = shipped.path(documents.GUIDANCE)
    texts = {**_skills(shipped),
             **{f"the workflow guidance's {path.relative_to(guidance).as_posix()}":
                path.read_text("utf-8") for path in sorted(guidance.rglob("*.md"))}}

    assert any(_ID.search(text) for text in texts.values()), "nothing cites a requirement"
    assert unheld_ids(texts, shipped.path(documents.SPECIFICATION).read_text("utf-8")) == []


def test_a_skill_cites_a_requirement_the_specification_lacks() -> None:
    """CW-lm42: a cited id the specification does not hold fails, naming the skill and
    the id; one inside a longer word is no citation."""
    specification = "### Requirement: CW-r6kd No step writes the protected paths\n"
    texts = {"change-implement": "as CW-r6kd and CW-zz99 say, not XCW-ab12 or CW-ab12x"}

    assert unheld_ids(texts, specification) == [
        "change-implement cites CW-zz99, which the shipped specification does not hold"]
