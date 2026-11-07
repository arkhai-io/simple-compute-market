"""Every make target and repository path the workflow's skills, its step table, and its
make fragment name is one this repository says it provides, and each role the workflow
asks of an adopting repository has a provision here.

The roles are stated twice: in `change-workflow`'s `README.md`, what any adopting
repository provides, and in `market-change-workflow`'s, how this one provides each.
This repository provides them in two places: its workflow configuration,
`.agents/workflow.toml`, whose hooks' and validation parts' commands are provisions as
they stand, and its statement of what the configuration does not hold. This test reads
the configuration's commands and the two documents' tables, never the engine's
modules: whether the table of the engine's own assumptions is complete is review's to
judge, and the engine checks the configuration itself whenever it reads it.

A name is collected from code, never from prose: a skill's code spans and fenced
blocks, each rule of the step table, and the fragment's text and the targets it
defines. A make target is the first word after `make` and its flags, kept with the
directory `-C` names; a repository path is a word under a directory Git tracks at the
repository's root, or a file there, its heading anchor or line number dropped. A path
the repository does not track, such as validation's output directory, is listed by
the documents but not collected, since whether it exists depends on the checkout.
"""

from __future__ import annotations

import functools
import re
import subprocess
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents/skills"
# The workflow's skills: one per step, and the guidance review, which no step runs.
# The `openspec-*` skills beside them are OpenSpec's own, not the workflow's.
WORKFLOW_SKILLS = ("change-*/SKILL.md", "guidance-review/SKILL.md")
STEP_TABLE = ROOT / ".claude/change-steps.toml"
FRAGMENT = ROOT / "scripts/change_workflow/workflow.mk"
ROLES = ROOT / "openspec/specs/change-workflow/README.md"
PROVISIONS = ROOT / "openspec/specs/market-change-workflow/README.md"
CONFIGURATION = ROOT / ".agents/workflow.toml"
ROLES_HEADING = "What an adopting repository provides"
PROVISIONS_HEADING = "How this repository provides the workflow's roles"

# An inline code span, of one backtick or more, which may wrap across lines.
_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
_FENCE = re.compile(r"^\s*(```|~~~)")
_TARGET = re.compile(r"^[a-z][a-z0-9_*.-]*$")
# A rule of a makefile: its target, then a colon that is no assignment's.
_RULE = re.compile(r"^(?P<target>[a-z][a-z0-9_-]*):(?!=)", re.M)
_TRAILING = ".,;:)]}'\""
_LEADING = "([{'\"$"


@dataclass(frozen=True)
class Root:
    """The entries at a repository's root a path may begin with."""

    directories: frozenset[str]
    files: frozenset[str]


@functools.cache
def tracked_root() -> Root:
    """The directories and files Git tracks at this repository's root. `README.md` is
    left out: a skill naming it means a capability's, which every capability directory
    may hold."""
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True,
                             text=True).stdout.split()
    return Root(frozenset(path.split("/", 1)[0] for path in tracked if "/" in path),
                frozenset(path for path in tracked if "/" not in path) - {"README.md"})


def code_of(markdown: str) -> list[str]:
    """The code a Markdown document holds: each inline span, one wrapped across lines
    included, and each fenced block's lines."""
    code: list[str] = []
    prose: list[str] = []
    fenced = False

    def spans() -> None:
        code.extend(" ".join(match[2].split()) for match in _SPAN.finditer("\n".join(prose)))
        prose.clear()

    for line in markdown.splitlines():
        if _FENCE.match(line):
            if not fenced:
                spans()
            fenced = not fenced
        elif fenced:
            code.append(line)
        else:
            prose.append(line)
    spans()
    return code


def _words(text: str) -> list[str]:
    return [word.rstrip(_TRAILING).lstrip(_LEADING) for word in re.split(r"[\s(]+", text)]


def make_targets(text: str) -> list[str]:
    """Each `make` command's target in `text`, as `make <target>` or
    `make -C <directory> <target>`."""
    words, found = _words(text), []
    for index, word in enumerate(words):
        if word != "make":
            continue
        directory, at = None, index + 1
        while at < len(words) and (words[at].startswith("-") or "=" in words[at]):
            if words[at] == "-C" and at + 1 < len(words):
                directory, at = words[at + 1], at + 2
            else:
                at += 1
        if at < len(words) and _TARGET.match(words[at]):
            found.append(f"make -C {directory} {words[at]}" if directory
                         else f"make {words[at]}")
    return found


def paths(text: str, root: Root) -> list[str]:
    """Each repository path in `text`, its anchor and line number dropped: a path
    under a directory at `root`, or a file there. A bare directory's name is none,
    since in code it is a command (`openspec`) or a `-C` argument."""
    found = []
    for word in _words(text):
        path = re.sub(r":\d+$", "", word.split("#", 1)[0])
        first, slash, _ = path.partition("/")
        if (slash and first in root.directories) or path in root.files:
            found.append(path)
    return found


def _shown(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def collected(root: Root, skills: Path = SKILLS, step_table: Path = STEP_TABLE,
              fragment: Path = FRAGMENT) -> dict[str, set[str]]:
    """Every make target and repository path the skills, the step table, and the
    fragment name, the targets the fragment defines among them, each with where it is
    named."""
    where: dict[str, set[str]] = defaultdict(set)
    sources: list[tuple[str, list[str]]] = [
        (_shown(skill), code_of(skill.read_text("utf-8")))
        for skill in sorted(path for pattern in WORKFLOW_SKILLS for path in skills.glob(pattern))]
    table = tomllib.loads(step_table.read_text("utf-8"))
    # A step's rules are under `[steps.<name>]`, the shared ones under `[common]`.
    rows = [table.get("common", {}), *table.get("steps", {}).values()]
    rules = [rule for row in rows for key in ("allow", "deny") for rule in row.get(key, [])]
    sources.append((_shown(step_table), rules))
    text = fragment.read_text("utf-8")
    sources.append((_shown(fragment), text.splitlines()))
    for name, texts in sources:
        for code in texts:
            for found in (*make_targets(code), *paths(code, root)):
                where[found].add(name)
    for rule in _RULE.finditer(text):
        where[f"make {rule['target']}"].add(_shown(fragment))
    return where


def section(markdown: str, heading: str) -> str:
    """The text under the `##` or `###` heading `heading`, to the next heading of its
    level or above."""
    match = re.search(rf"^(#{{2,3}}) {re.escape(heading)}\s*$", markdown, re.M)
    if match is None:
        raise AssertionError(f"no heading {heading!r}")
    level = len(match[1])
    rest = markdown[match.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[:end.start()] if end else rest


def _tables(text: str) -> list[list[list[str]]]:
    """Each Markdown table in `text`, as its body rows of cells."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            current = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        if current is None:
            current = []
            tables.append(current)
            continue
        current.append(cells)
    return tables


def roles(markdown: str, heading: str) -> list[str]:
    """The roles a document states under `heading`: its first table's first cells."""
    tables = _tables(section(markdown, heading))
    return [row[0] for row in tables[0]] if tables else []


def provided(markdown: str, heading: str, root: Root) -> set[str]:
    """Every make target and path the tables under `heading` list, as code."""
    listed: set[str] = set()
    for table in _tables(section(markdown, heading)):
        for row in table:
            for code in (match[2] for cell in row[1:] for match in _SPAN.finditer(cell)):
                listed.update(make_targets(code))
                listed.update(paths(code, root))
    return listed


def configured(text: str, root: Root) -> set[str]:
    """Every make target and path the configuration's commands name: each hook's, the
    validation preflight's, and each part's `run`, `start`, `collect`, and `cleanup`,
    each a command or a list of them."""
    def each(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        return [command for command in value if isinstance(command, str)] \
            if isinstance(value, list) else []

    configuration = tomllib.loads(text)
    validation = configuration.get("validation", {})
    commands = [command for value in configuration.get("hooks", {}).values()
                for command in each(value)]
    commands += each(validation.get("preflight"))
    for part in validation.get("parts", {}).values():
        for key in ("run", "start", "collect", "cleanup"):
            commands += each(part.get(key))
    listed: set[str] = set()
    for command in commands:
        listed.update(make_targets(command))
        listed.update(paths(command, root))
    return listed


def unlisted(where: dict[str, set[str]], listed: set[str]) -> list[str]:
    return [f"{name} (named in {', '.join(sorted(where[name]))})"
            for name in sorted(set(where) - listed)]


def role_problems(general: str, here: str) -> list[str]:
    """Each role the workflow states that this repository provides no way to fill,
    and each provision for a role the workflow does not state."""
    stated, provided_for = roles(general, ROLES_HEADING), roles(here, PROVISIONS_HEADING)
    if not stated:
        return ["the workflow states no role"]
    return ([f"no provision for the role {role!r}" for role in stated
             if role not in provided_for]
            + [f"a provision for {role!r}, which the workflow states no role for"
               for role in provided_for if role not in stated])


def listed_here(root: Root) -> set[str]:
    """What this repository provides: its statement's tables and its configuration's
    commands."""
    return (provided(PROVISIONS.read_text("utf-8"), PROVISIONS_HEADING, root)
            | configured(CONFIGURATION.read_text("utf-8"), root))


def test_every_target_and_path_the_workflow_names_is_provided_here() -> None:
    root = tracked_root()

    missing = unlisted(collected(root), listed_here(root))

    assert not missing, "this repository's provision of the workflow's roles does not " \
                        "list:\n" + "\n".join(missing)


def test_each_role_has_a_provision_and_each_provision_a_role() -> None:
    problems = role_problems(ROLES.read_text("utf-8"), PROVISIONS.read_text("utf-8"))

    assert not problems, "\n".join(problems)


# The collection itself, on texts and trees of the test's own.

ROOT_OF_TEST = Root(frozenset({"openspec", "docs", ".agents", "helm"}),
                    frozenset({"AGENTS.md", "Makefile"}))


def test_a_target_is_read_from_code_with_its_directory() -> None:
    assert make_targets("make -C helm test-render") == ["make -C helm test-render"]
    assert make_targets("make -s --no-print-directory check-change CHANGE=x") == [
        "make check-change"]
    assert make_targets("Bash(make -C * test*)") == ["make -C * test*"]
    assert make_targets("make") == []


def test_prose_names_no_target() -> None:
    assert code_of("Do not make the change; run `make test` and\n```\nmake lock\n```\n") == [
        "make test", "make lock"]


def test_a_span_wrapped_across_lines_is_read_whole() -> None:
    assert code_of("never `make -C <a\n  checkout>`: such as `make -C\nhelm test-render`.") == [
        "make -C <a checkout>", "make -C helm test-render"]


def test_a_double_backtick_span_leaves_the_spans_after_it_whole() -> None:
    assert code_of("its ``<name>` (phase)`` form; then `make check-change`.") == [
        "<name>` (phase)", "make check-change"]


def test_a_path_is_rooted_in_the_repository() -> None:
    assert paths("openspec/README.md#plan-closeout-requirements, notes.md:57",
                 ROOT_OF_TEST) == ["openspec/README.md"]
    assert paths("Edit(docs/**)", ROOT_OF_TEST) == ["docs/**"]
    assert paths(".agents/change-outcome.schema.json AGENTS.md.", ROOT_OF_TEST) == [
        ".agents/change-outcome.schema.json", "AGENTS.md"]
    assert paths("README.md reviews/ ../*-proposal/** openspec validate helm",
                 ROOT_OF_TEST) == []


def _sources(tmp_path: Path, skill: str = "", table: str = "", fragment: str = "") -> dict:
    (tmp_path / "skills/change-extra").mkdir(parents=True)
    (tmp_path / "skills/change-extra/SKILL.md").write_text(skill, "utf-8")
    (tmp_path / "table.toml").write_text(table, "utf-8")
    (tmp_path / "workflow.mk").write_text(fragment, "utf-8")
    return collected(ROOT_OF_TEST, tmp_path / "skills", tmp_path / "table.toml",
                     tmp_path / "workflow.mk")


def test_a_skill_naming_an_unlisted_target_is_named(tmp_path: Path) -> None:
    """CW-m4ps's "A skill names a new target", against what this repository provides:
    its statement and its configuration's commands, the latter alone providing
    validation's preflight, `make check-uv-version`."""
    assert "make check-uv-version" not in provided(PROVISIONS.read_text("utf-8"),
                                                   PROVISIONS_HEADING, tracked_root())
    where = _sources(tmp_path, skill="Run `make check-something`, then `make test`, then "
                                     "`make check-uv-version`.\n")

    missing = unlisted(where, listed_here(tracked_root()))

    assert missing == [f"make check-something (named in "
                       f"{tmp_path / 'skills/change-extra/SKILL.md'})"]


def test_the_guidance_review_is_read_and_openspecs_own_skills_are_not(tmp_path: Path) -> None:
    for name, text in (("guidance-review", "Append to `openspec/changes/archive/x.jsonl`.\n"),
                       ("openspec-propose", "Run `make check-something`.\n")):
        (tmp_path / "skills" / name).mkdir(parents=True)
        (tmp_path / "skills" / name / "SKILL.md").write_text(text, "utf-8")

    where = _sources(tmp_path)

    assert set(where) == {"openspec/changes/archive/x.jsonl"}


def test_the_step_table_and_the_fragment_name_their_targets_and_paths(tmp_path: Path) -> None:
    where = _sources(
        tmp_path,
        table='[common]\nallow = ["Bash(make lock*)", "Edit(openspec/**)"]\n'
              '[steps.plan]\ndeny = ["Bash(make -C helm teardown*)"]\n',
        fragment="# Included by a repository's Makefile.\nCHANGE_WORKFLOW ?= x\n"
                 "design: ## A step\n\t@$(CHANGE_WORKFLOW) start design\n")

    assert set(where) == {"make lock*", "openspec/**", "make -C helm teardown*", "Makefile",
                          "make design"}
    assert where["make design"] == {str(tmp_path / "workflow.mk")}


def test_the_configurations_commands_are_provisions() -> None:
    """A hook's commands, the preflight's, and each part's are what the configuration
    provides; a document it loads or a value it holds is not a command."""
    text = """
[repository]
inert-paths = ["docs/"]
[hooks]
pre-commit = "make check-repository CHANGE={change}"
pre-commit-functional = ["make test", "make check-packaging"]
[load]
common = ["AGENTS.md"]
[validation]
preflight = ["make check-uv-version"]
[validation.parts.helm]
run = "make validate-helm CHANGE={change}"
evidence = ".snapshot/validation/"
cleanup = ["make -C helm teardown CHANGE={change}"]
"""

    assert configured(text, ROOT_OF_TEST) == {
        "make check-repository", "make test", "make check-packaging",
        "make check-uv-version", "make validate-helm", "make -C helm teardown"}


def test_a_role_with_no_provision_is_named() -> None:
    general = "## What an adopting repository provides\n\n| Role | Used by |\n|---|---|\n" \
              "| A role | design |\n| Another role | plan |\n"
    here = "## How this repository provides the workflow's roles\n\n| Role | Provided by |\n" \
           "|---|---|\n| A role | `make x` |\n| A third role | `make y` |\n"

    assert role_problems(general, here) == [
        "no provision for the role 'Another role'",
        "a provision for 'A third role', which the workflow states no role for"]
