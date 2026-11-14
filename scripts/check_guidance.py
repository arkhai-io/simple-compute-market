#!/usr/bin/env python3
"""Fail where the repository's guidance breaks the rules that keep it layered.

Guidance divides into three layers — engineering, the change workflow's, and this
repository's — and a lower layer never links to a higher one
(docs/guidance/workflow/README.md, "The layers of guidance"). This check holds every
guidance file to that model.

The guidance set is found by place before any frontmatter is read, so a guide that
forgot its tags fails rather than escaping: every Markdown file under
`docs/guidance/`; every Markdown file in a capability's directory under
`openspec/specs/` but its `spec.md`, its companion (`architecture.md`, or
`README.md` where the capability has an `index.md`), and its `index.md`; every other
Markdown file outside `openspec/changes/` whose frontmatter carries `tags`; and the
documents `AGENTS.md`'s layer table (its `Layer | Guidance` table) names. No layer is
read from a directory: a file's frontmatter alone states its layer and tags.

It fails, naming the file, on a guidance file with no `tags`; on zero or several
layer tags; on a tag that neither its layer's vocabulary table nor a lower layer's
defines; on a vocabulary row no guidance file carries; on a malformed vocabulary or
exception table; on an exception row citing no guidance file or naming a kind other
than `selects` or `overrides`; and on a link from a guidance file to one tagged with
a higher layer. A layer's vocabulary is the table under a heading "Tags" whose first
row is that layer's tag; an exception table is the table under a heading
"Exceptions to shared guidance". It also fails on a citation of a guidance file — a
Markdown link, or a path quoted in backticks or double quotes — whose anchor names
no heading in that file, in any Markdown file Git tracks or would track outside the
archived changes and `docs/prompts/`: an archived change keeps the citations it was
written with, and the deprecated prompts are left as they are. Headings are slugged
as GitHub renders their anchors.

`--list [--tag <tag>]` prints each guidance file with its tags, and
`--list-exceptions` every exception row, so whatever reads the set later reads it
from here rather than finding it again.

Run by `make check-repository`, the change workflow's `pre-commit`. Usage:
`check_guidance.py [--list [--tag <tag>] | --list-exceptions]`.

Contract: openspec/specs/market-change-workflow/spec.md, MCW-c4ek; the rules it
checks are openspec/specs/change-workflow/spec.md's CW-g7lt, CW-d2rw, CW-x4ex,
CW-n6dm, and CW-r8cg.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Sequence
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

# The layers, lowest first: a file may carry a tag of its own layer's vocabulary or a
# lower one's, and may link to guidance of its own layer or a lower one.
LAYERS = ("engineering", "workflow", "repository")
SHARED = "docs/guidance/"
SPECS = "openspec/specs/"
CHANGES = "openspec/changes/"
# Where the anchor check does not look.
UNCHECKED = ("openspec/changes/archive/", "docs/prompts/")
ENTRY = "AGENTS.md"
LAYER_TABLE = ("Layer", "Guidance")
TAGS_HEADING = "Tags"
TAG_COLUMNS = ("Tag", "Kind", "Description")
EXCEPTIONS_HEADING = "Exceptions to shared guidance"
EXCEPTION_COLUMNS = ("Shared rule", "Kind", "Here", "Reason")
EXCEPTION_KINDS = ("selects", "overrides")

# A fence may be indented, as one inside a list item is; only a fence with no info
# string closes one.
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_CLOSING_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
_CLOSING_HASHES = re.compile(r"\s+#+\s*$")
_HTML_ANCHOR = re.compile(r"<[a-z][a-z0-9]*\s[^>]*?\b(?:id|name)\s*=\s*[\"']([^\"']+)[\"']",
                          re.I)
_EMPHASIS = re.compile(r"(?<![\w*])([*_]{1,3})(?=\S)(.+?)(?<=\S)\1(?![\w*])")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_LINK = re.compile(r"\]\(\s*<?([^)\s>]*)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
_QUOTED = re.compile(r"([`\"])((?:[\w.-]+/)*[\w.-]+\.md)#([^`\"\s]+)\1")
_TAG = re.compile(r"^`([a-z0-9][a-z0-9-]*)`$")
_DELIMITER = re.compile(r"^:?-+:?$")
_TAGS_KEY = re.compile(r"^tags\s*:(.*)$")

# Every Markdown file Git tracks or would track, relative to the root.
Lister = Callable[[Path], list[str]]


def repository_files(root: Path) -> list[str]:
    """Every Markdown file Git tracks or would track: tracked, and untracked but not
    ignored, so a guide written and not yet added is checked before it is
    committed. A tracked file deleted from the worktree is not one."""
    listed = subprocess.run(["git", "ls-files", "-z", "--cached", "--others",
                             "--exclude-standard", "--", "*.md"], cwd=root,
                            capture_output=True, text=True, check=True)
    return sorted({path for path in listed.stdout.split("\0")
                   if path and (root / path).is_file()})


def prose(text: str) -> Iterator[tuple[int, str]]:
    """Each line of a Markdown document that renders as prose, numbered from 1:
    neither its frontmatter nor a fenced code block, whose headings and links are no
    headings or links."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")),
                   None)
        if end is not None:
            start = end + 1
    fence: str | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if fence is None and (opened := _FENCE.match(line)):
            fence = opened.group(1)
        elif fence is not None:
            closed = _CLOSING_FENCE.match(line)
            if closed and closed.group(1)[0] == fence[0] and len(closed.group(1)) >= len(fence):
                fence = None
        else:
            yield index + 1, line


class FrontmatterError(ValueError):
    """The frontmatter's `tags` is no list."""


def frontmatter_tags(text: str) -> list[str] | None:
    """The `tags` of a document's YAML frontmatter, as a flow list (`[a, b]`) or a
    block list; None when it has no frontmatter or no `tags` key."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    if end is None:
        return None
    block = lines[1:end]
    for index, line in enumerate(block):
        key = _TAGS_KEY.match(line)
        if not key:
            continue
        value = key.group(1).strip()
        if value.startswith("[") and value.endswith("]"):
            return [item.strip().strip("'\"") for item in value[1:-1].split(",")
                    if item.strip()]
        if not value:
            items = []
            for later in block[index + 1:]:
                item = re.match(r"^\s*-\s+(.*?)\s*$", later)
                if not item:
                    break
                items.append(item.group(1).strip("'\""))
            return items
        raise FrontmatterError(f"its frontmatter's tags must be a list, as [{value}]; "
                               f"got {value!r}")
    return None


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading: its rendered text lower-cased, every
    character but letters, digits, marks, `-`, `_`, and spaces removed, and each space
    a `-`. Rendered, a code span keeps its text as written, `<…>` and underscores
    included, while outside one a link is its text, an HTML tag nothing, and
    emphasis its words."""
    rendered = []
    for index, part in enumerate(re.split(r"(`+[^`]*?`+)", heading)):
        if index % 2:
            rendered.append(part.strip("`"))
            continue
        part = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", part)
        part = re.sub(r"<[^>]+>", "", part)
        rendered.append(_EMPHASIS.sub(r"\2", part))
    text = "".join(rendered).strip().lower()
    kept = "".join(ch for ch in text
                   if ch in " -_" or unicodedata.category(ch)[0] in "LNM")
    return kept.replace(" ", "-")


def anchors(text: str) -> set[str]:
    """Every anchor a document offers: each heading's slug, a repeated one numbered as
    GitHub numbers it (`-1`, `-2`), and each HTML anchor's `id` or `name`."""
    found: set[str] = set()
    seen: dict[str, int] = {}
    for _, line in prose(text):
        found.update(_HTML_ANCHOR.findall(line))
        heading = _HEADING.match(line)
        if not heading:
            continue
        name = slug(_CLOSING_HASHES.sub("", heading.group(2)))
        count = seen.get(name, 0)
        seen[name] = count + 1
        found.add(name if count == 0 else f"{name}-{count}")
    return found


def cells(line: str) -> list[str] | None:
    """A table line's cells, split on every `|` not escaped, as GitHub splits them;
    None for a line that is no table line."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]


@dataclass
class Table:
    """The first table under a heading: its header, its rows, and where it starts."""

    line: int
    header: list[str]
    delimiter: list[str]
    rows: list[list[str]] = field(default_factory=list)


def tables_under(text: str, heading: str) -> list[tuple[int, Table | None]]:
    """For each heading named `heading`, at any level, its line and the first table
    before the next heading, or None when it holds none."""
    found: list[tuple[int, Table | None]] = []
    current: tuple[int, Table | None] | None = None
    in_table = False
    for number, line in prose(text):
        named = _HEADING.match(line)
        if named:
            if current is not None:
                found.append(current)
            current = ((number, None) if _CLOSING_HASHES.sub("", named.group(2)) == heading
                       else None)
            in_table = False
            continue
        if current is None:
            continue
        row = cells(line)
        table = current[1]
        if row is None:
            if table is not None and in_table:
                found.append(current)
                current = None
            in_table = False
            continue
        if table is None:
            current = (current[0], Table(number, row, []))
            in_table = True
        elif in_table and not table.delimiter:
            table.delimiter = row
        elif in_table:
            table.rows.append(row)
    if current is not None:
        found.append(current)
    return found


def _table_shape(table: Table | None, columns: tuple[str, ...]) -> str | None:
    """Why a table is malformed, or None: it must have the columns given, a delimiter
    row, and that many cells in every row."""
    if table is None:
        return "holds no table"
    if tuple(table.header) != columns:
        return (f"its header is | {' | '.join(table.header)} |, not "
                f"| {' | '.join(columns)} |")
    if len(table.delimiter) != len(columns) or not all(_DELIMITER.match(cell)
                                                        for cell in table.delimiter):
        return "its second line is no delimiter row"
    for row in table.rows:
        if len(row) != len(columns):
            return f"the row | {' | '.join(row)} | has {len(row)} cells, not {len(columns)}"
    return None


def _without_code(line: str) -> str:
    return _CODE_SPAN.sub("", line)


def _resolve(source: str, target: str) -> str | None:
    """A link's target path relative to the root, from the document `source` links
    from; None for a target outside the repository or one no file can be."""
    if target.startswith("/"):
        joined = target.lstrip("/")
    else:
        joined = posixpath.join(posixpath.dirname(source), target)
    resolved = posixpath.normpath(joined)
    if resolved.startswith("../") or resolved == "..":
        return None
    return resolved


def links(source: str, text: str) -> Iterator[tuple[int, str, str | None]]:
    """Each Markdown link a document makes, inline or by reference, outside code: its
    line, its target path relative to the root (`source` itself for an anchor alone),
    and its anchor, or None."""
    for number, line in prose(text):
        targets = _LINK.findall(_without_code(line))
        reference = _REFERENCE.match(line)
        if reference:
            targets.append(reference.group(1))
        for target in targets:
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            path, _, anchor = target.partition("#")
            resolved = source if not path else _resolve(source, unquote(path))
            if resolved is not None:
                yield number, resolved, unquote(anchor) if anchor else None


def quoted(source: str, text: str, known: set[str]) -> Iterator[tuple[int, str, str]]:
    """Each Markdown file's path quoted with an anchor, in backticks or double quotes,
    as the root names it or, failing that, as the quoting document's directory does:
    its line, its path relative to the root, and its anchor."""
    for number, line in prose(text):
        for _, path, anchor in _QUOTED.findall(line):
            resolved = path if path in known else _resolve(source, path)
            if resolved is not None:
                yield number, resolved, unquote(anchor)


@dataclass
class Guidance:
    """The guidance as read: each file's tags (None when it carries none), each
    layer's vocabulary, its exception rows, and what is wrong with it."""

    tags: dict[str, list[str] | None] = field(default_factory=dict)
    # Each layer's vocabulary: its file, and each tag it defines with that tag's kind.
    vocabularies: dict[str, tuple[str, dict[str, str]]] = field(default_factory=dict)
    # Each exception row: its file, its kind, its shared rule, and what it does here.
    exceptions: list[tuple[str, str, str, str]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def layer(self, path: str) -> str | None:
        """The one layer tag a guidance file carries, or None when it carries no tags,
        none, or several."""
        carried = [tag for tag in self.tags.get(path) or () if tag in LAYERS]
        return carried[0] if len(carried) == 1 else None


def _layer_table_documents(root: Path, files: Sequence[str],
                           problems: list[str]) -> set[str]:
    """The documents the root guidance's layer table names, a directory standing for
    the Markdown files beneath it; a document it names that does not exist is a
    problem."""
    entry = root / ENTRY
    if not entry.is_file():
        return set()
    found: set[str] = set()
    in_table = False
    for number, line in prose(entry.read_text("utf-8")):
        row = cells(line)
        if row is None or not in_table:
            in_table = row is not None and tuple(row) == LAYER_TABLE
            continue
        if len(row) != len(LAYER_TABLE) or _DELIMITER.match(row[1]):
            continue
        for target in _LINK.findall(row[1]) or re.findall(r"`([^`]+)`", row[1]):
            path = _resolve(ENTRY, unquote(target.partition("#")[0]))
            if path is None:
                continue
            if (root / path).is_dir():
                found.update(f for f in files if f.startswith(path.rstrip("/") + "/"))
            elif (root / path).is_file():
                found.add(path)
            else:
                problems.append(f"{ENTRY}:{number}: the layer table names {target}, which "
                                "does not exist")
    return found


def _capability_guidance(root: Path, path: str) -> bool:
    """Whether `path` lies in a capability's directory and is neither its
    specification, its companion, nor its index."""
    if not path.startswith(SPECS):
        return False
    parts = path[len(SPECS):].split("/")
    if len(parts) < 2:
        return False
    capability = root / SPECS / parts[0]
    if len(parts) == 2:
        name = parts[1]
        if name in ("spec.md", "index.md", "architecture.md"):
            return False
        if name == "README.md" and (capability / "index.md").is_file():
            return False
    return True


def guidance_set(root: Path, files: Sequence[str], problems: list[str]) -> list[str]:
    """The guidance files, found by place, by their tags outside the changes, and by
    the root guidance's layer table."""
    found = set(_layer_table_documents(root, files, problems))
    for path in files:
        if path.startswith(SHARED) or _capability_guidance(root, path):
            found.add(path)
        elif not path.startswith(CHANGES):
            try:
                if frontmatter_tags((root / path).read_text("utf-8")) is not None:
                    found.add(path)
            except FrontmatterError:
                found.add(path)
    return sorted(found)


def _vocabulary(path: str, number: int, table: Table | None, guidance: Guidance) -> None:
    """Read one vocabulary table into `guidance`, or record why it is malformed."""
    where = f"{path}:{number}: the table under \"{TAGS_HEADING}\""
    if shape := _table_shape(table, TAG_COLUMNS):
        guidance.problems.append(f"{where} is malformed: {shape}")
        return
    assert table is not None
    defined: dict[str, str] = {}
    for row in table.rows:
        tag, kind, description = row
        name = _TAG.match(tag)
        if not name or not re.fullmatch(r"[a-z]+", kind) or not description:
            guidance.problems.append(
                f"{where} is malformed: the row | {' | '.join(row)} | needs a tag in "
                "backticks, a one-word kind, and a description")
            return
        if name.group(1) in defined:
            guidance.problems.append(f"{where} is malformed: it defines {name.group(1)} twice")
            return
        defined[name.group(1)] = kind
    if not defined or next(iter(defined.values())) != "layer" \
            or next(iter(defined)) not in LAYERS:
        guidance.problems.append(f"{where} is malformed: its first row must be a layer tag, "
                                 f"one of {', '.join(LAYERS)}, of kind layer")
        return
    layer = next(iter(defined))
    if [tag for tag, kind in defined.items() if kind == "layer"] != [layer]:
        guidance.problems.append(f"{where} is malformed: only its first row is a layer tag")
        return
    if layer in guidance.vocabularies:
        guidance.problems.append(f"{where} is a second vocabulary of the {layer} layer, "
                                 f"beside {guidance.vocabularies[layer][0]}'s")
        return
    guidance.vocabularies[layer] = (path, defined)


def _exceptions(path: str, number: int, table: Table | None, guidance: Guidance,
                members: set[str]) -> None:
    """Read one exception table into `guidance`, or record what is wrong with it."""
    where = f"{path}:{number}: the table under \"{EXCEPTIONS_HEADING}\""
    if shape := _table_shape(table, EXCEPTION_COLUMNS):
        guidance.problems.append(f"{where} is malformed: {shape}")
        return
    assert table is not None
    for row in table.rows:
        rule, kind, here, _ = row
        if kind not in EXCEPTION_KINDS:
            guidance.problems.append(f"{path}:{table.line}: an exception row names the kind "
                                     f"{kind!r}, not {' or '.join(EXCEPTION_KINDS)}: {rule}")
        cited = {resolved for _, resolved, _ in links(path, rule) if resolved in members}
        if not cited:
            guidance.problems.append(f"{path}:{table.line}: an exception row cites no "
                                     f"guidance file: {rule}")
        guidance.exceptions.append((path, kind, rule, here))


def read_guidance(root: Path, files: Sequence[str]) -> tuple[Guidance, dict[str, str]]:
    """The guidance set as read, and each guidance file's text."""
    guidance = Guidance()
    members = guidance_set(root, files, guidance.problems)
    texts = {path: (root / path).read_text("utf-8") for path in members}
    for path in members:
        try:
            guidance.tags[path] = frontmatter_tags(texts[path])
        except FrontmatterError as exc:
            guidance.tags[path] = None
            guidance.problems.append(f"{path}: {exc}")
            continue
        if guidance.tags[path] is None:
            guidance.problems.append(f"{path}: has no tags in its frontmatter; a guidance "
                                     f"file carries one layer tag, one of {', '.join(LAYERS)}")
    for path in members:
        for number, table in tables_under(texts[path], TAGS_HEADING):
            _vocabulary(path, number, table, guidance)
        for number, table in tables_under(texts[path], EXCEPTIONS_HEADING):
            _exceptions(path, number, table, guidance, set(members))
    return guidance, texts


def _check_tags(guidance: Guidance) -> None:
    """Each file's layer tag and other tags against the vocabularies, and each
    vocabulary row against the tags carried."""
    carried: set[str] = set()
    for path, tags in guidance.tags.items():
        if tags is None:
            continue
        carried.update(tags)
        layers = [tag for tag in tags if tag in LAYERS]
        if not layers:
            guidance.problems.append(f"{path}: carries no layer tag; a guidance file carries "
                                     f"one of {', '.join(LAYERS)}")
            continue
        if len(layers) > 1:
            guidance.problems.append(f"{path}: carries several layer tags, "
                                     f"{', '.join(layers)}; a guidance file carries one")
            continue
        rank = LAYERS.index(layers[0])
        if layers[0] not in guidance.vocabularies:
            guidance.problems.append(f"{path}: carries the layer tag {layers[0]}, which no "
                                     f"vocabulary table defines")
            continue
        allowed = {tag for layer in LAYERS[:rank + 1] if layer in guidance.vocabularies
                   for tag in guidance.vocabularies[layer][1]}
        for tag in tags:
            if tag in LAYERS or tag in allowed:
                continue
            higher = next((layer for layer in LAYERS[rank + 1:]
                           if tag in guidance.vocabularies.get(layer, ("", {}))[1]), None)
            guidance.problems.append(
                f"{path}: carries the tag {tag}, which "
                + (f"only the {higher} vocabulary, a higher layer's, defines" if higher
                   else f"neither the {layers[0]} vocabulary nor a lower layer's defines"))
    for layer, (path, defined) in guidance.vocabularies.items():
        guidance.problems.extend(f"{path}: the {layer} vocabulary's tag {tag} is carried "
                                 "by no guidance file"
                                 for tag in defined if tag not in carried)


def _check_links(guidance: Guidance, texts: dict[str, str]) -> None:
    """No guidance file links to one tagged with a higher layer."""
    for path, text in texts.items():
        layer = guidance.layer(path)
        if layer is None:
            continue
        for number, target, _ in links(path, text):
            linked = guidance.layer(target)
            if linked is not None and LAYERS.index(linked) > LAYERS.index(layer):
                guidance.problems.append(f"{path}:{number}: links to {target}, a guidance file "
                                         f"tagged {linked}, from a file tagged {layer}, a lower "
                                         "layer")


def _check_anchors(root: Path, files: Sequence[str], guidance: Guidance,
                   texts: dict[str, str]) -> None:
    """Every citation of a guidance file with an anchor names a heading in it."""
    members = set(guidance.tags)
    offered: dict[str, set[str]] = {}
    for path in files:
        if path.startswith(UNCHECKED):
            continue
        text = texts.get(path)
        if text is None:
            text = (root / path).read_text("utf-8", errors="replace")
        cited = [(number, target, anchor) for number, target, anchor in links(path, text)
                 if anchor is not None]
        cited += list(quoted(path, text, members))
        for number, target, anchor in cited:
            if target not in members:
                continue
            if target not in offered:
                offered[target] = anchors(texts[target])
            if anchor not in offered[target] and anchor.lower() not in offered[target]:
                guidance.problems.append(f"{path}:{number}: cites {target}#{anchor}, and no "
                                         f"heading of {target} has that anchor")


def check(root: Path, files: Sequence[str]) -> Guidance:
    """The guidance as read, every problem found recorded on it."""
    guidance, texts = read_guidance(root, files)
    _check_tags(guidance)
    _check_links(guidance, texts)
    _check_anchors(root, files, guidance, texts)
    # A path quoted inside a link's text is cited twice on one line, and said once.
    guidance.problems = list(dict.fromkeys(guidance.problems))
    return guidance


def main(argv: Sequence[str] | None = None, root: Path = ROOT,
         lister: Lister = repository_files) -> int:
    parser = argparse.ArgumentParser(prog="check_guidance.py", description=__doc__.split(
        "\n\n")[0])
    listing = parser.add_mutually_exclusive_group()
    listing.add_argument("--list", action="store_true",
                         help="print each guidance file with its tags")
    listing.add_argument("--list-exceptions", action="store_true",
                         help="print every exception row")
    parser.add_argument("--tag", help="with --list, only the files carrying this tag")
    args = parser.parse_args(argv)
    if args.tag and not args.list:
        parser.error("--tag needs --list")
    files = lister(root)
    if args.list:
        guidance, _ = read_guidance(root, files)
        for path, tags in guidance.tags.items():
            if args.tag is None or args.tag in (tags or ()):
                print(f"{path}: {', '.join(tags) if tags else '(no tags)'}")
        return 0
    if args.list_exceptions:
        guidance, _ = read_guidance(root, files)
        for path, kind, rule, here in guidance.exceptions:
            print(f"{path}: {kind}: {rule} — {here}")
        return 0
    guidance = check(root, files)
    if guidance.problems:
        print("\n".join(guidance.problems))
        print()
        print(f"FAIL: {len(guidance.problems)} problem(s) in the guidance: each file carries "
              "one layer tag and tags its layer's vocabulary or a lower one's defines, every "
              "vocabulary row is carried, every table is well formed, no guidance links to a "
              "higher layer, and every cited anchor names a heading.")
        return 1
    print(f"OK: {len(guidance.tags)} guidance files are tagged from their vocabularies, "
          f"{len(guidance.exceptions)} exception rows cite guidance, no guidance links to a "
          "higher layer, and every cited anchor names a heading.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
