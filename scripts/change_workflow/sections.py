"""The guidance a skill cites, by the name of a Markdown section.

A shipped skill cites the engineering guidance and the workflow's own guidance by
section name, never by a file, and the workflow's guidance cites the engineering
guidance so too: the engineering guidance is the user's, organized as they choose
beneath the checkout's pointer, and the workflow's ships beside the engine. A
citation takes one form, its names in double quotes, a line wrap anywhere in it:

    the engineering guidance's section "Imports go at module level"
    the workflow guidance's sections "Comment hygiene" and "Import placement"

A name resolves when exactly one heading of that text heads a section beneath the
guidance's directory. A name no heading carries, or several do, does not resolve;
`check config` reports either for the engineering guidance, refusing neither, since
a user's guidance is held to no repository's headings, and the distribution's own
test holds the workflow's guidance to what its skills cite.

Contract: openspec/specs/change-workflow/spec.md, CW-7x0z and CW-lm42.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Mapping

ENGINEERING, WORKFLOW = "engineering", "workflow"
# A citation of one guidance's sections: the phrase, then one quoted name or more,
# joined by commas, "and", or "or".
_CITATION = {
    guidance: re.compile(rf"\b{guidance}\s+guidance's\s+sections?\s+"
                         r'("[^"]+"(?:\s*(?:,|,?\s+and|,?\s+or)\s+"[^"]+")*)')
    for guidance in (ENGINEERING, WORKFLOW)}
_NAME = re.compile(r'"([^"]+)"')
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _shown(name: str) -> str:
    """A name as one line, however the citation wrapped it."""
    return " ".join(name.split())


def cited(text: str, guidance: str) -> set[str]:
    """The section names `text` cites of `guidance`, `ENGINEERING` or `WORKFLOW`."""
    return {_shown(name) for citation in _CITATION[guidance].finditer(text)
            for name in _NAME.findall(citation.group(1))}


def citing(texts: Mapping[str, str], guidance: str) -> dict[str, set[str]]:
    """Each section name the texts, by their names, cite of `guidance`, with the texts
    citing it."""
    found: dict[str, set[str]] = {}
    for source, text in texts.items():
        for name in cited(text, guidance):
            found.setdefault(name, set()).add(source)
    return found


def headings(text: str) -> list[str]:
    """The headings of a Markdown text, outside its fenced blocks, in order."""
    found, fenced = [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced and (match := _HEADING.match(line)):
            found.append(_shown(match.group(1)))
    return found


def heads(directory: Path) -> dict[str, list[Path]]:
    """Each heading beneath `directory`'s Markdown files, with the files carrying it,
    each relative to `directory`, once per section it heads."""
    found: dict[str, list[Path]] = {}
    for path in sorted(directory.rglob("*.md")):
        if path.is_file():
            for heading in headings(path.read_text("utf-8")):
                found.setdefault(heading, []).append(path.relative_to(directory))
    return found


def unresolved(names: Iterable[str], found: Mapping[str, list[Path]]
               ) -> dict[str, list[Path]]:
    """Each of `names` that does not resolve in `found`, with the files heading it:
    none for a name no heading carries, several for one that heads several sections."""
    return {name: found.get(name, []) for name in sorted(names)
            if len(found.get(name, [])) != 1}
