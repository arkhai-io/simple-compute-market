"""Every make target and repository path the workflow's skills name is the workflow's
own; every one its make fragment names is one this repository says it provides; and
each role the workflow asks of an adopting repository has a provision here.

A skill is shared by every repository that adopts the workflow, so it names no
repository's target or path (CW-n8tr): only the workflow's own — OpenSpec's tree as
the workflow knows it, the outcome schema the engine reads, and the make fragment's
targets — or one this repository's table of exemptions lists, each owned by the open
change that removes it. It cites the workflow's guidance and the engineering
guidance by section name, never by a file's path or name (CW-7x0z), and the engine
through its command, `change-workflow`. What a repository does not hold in common reaches a skill
through its configuration and its guides, never through the skill's text.

The roles are the workflow's, stated as structured output: `config --json` lists
them as `roles`, and the make fragment is the distribution's, at the path `fragment`
prints. This test reads both through the workflow's command, in a checkout holding no
configuration, so it needs no local configuration and parses no document of the
workflow's. This repository says how it provides each role in
`market-change-workflow`'s `README.md`, and provides them in two places: its workflow
configuration, `.agents/workflow.toml`, whose hooks' and evidence kinds' commands are
provisions as they stand, and its statement of what the configuration does not hold.
This test reads the configuration's commands and that statement's tables, never the
engine's modules: whether the table of the engine's own assumptions is complete is
review's to judge, and the engine checks the configuration itself whenever it reads
it.

A name is collected from code, never from prose: a skill's code spans and fenced
blocks, and the fragment's text and the targets it defines. A make target is the
first word after `make` and its flags, kept with the directory `-C` names; a repository path is a word under a directory Git tracks at the
repository's root, or a file there, its heading anchor or line number dropped. A path
the repository does not track, such as validation's output directory, is listed by
the documents but not collected, since whether it exists depends on the checkout. A
directory the provision of the guidance documents every step reads names, written
with its trailing `/`, provides every Markdown file beneath it; a directory any other
provision names provides only itself.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
import tempfile
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import workflow_command

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents/skills"
# The workflow's skills: one per step, and the guidance review, which no step runs.
# The `openspec-*` skills beside them are OpenSpec's own, not the workflow's.
WORKFLOW_SKILLS = ("change-*/SKILL.md", "guidance-review/SKILL.md")
PROVISIONS = ROOT / "openspec/specs/market-change-workflow/README.md"
CONFIGURATION = ROOT / ".agents/workflow.toml"
PROVISIONS_HEADING = "How this repository provides the workflow's roles"
GUIDANCE_ROLE = "The guidance documents every step reads"
EXEMPTIONS_HEADING = "What the workflow's skills name of this repository"

# OpenSpec's two trees as the workflow knows them: a change or a capability named by a
# placeholder, never by its name, beside the change index and the archive.
OPENSPEC = ("openspec/changes/", "openspec/specs/")
CHANGE_INDEX = "openspec/changes/README.md"
ARCHIVE = "archive"
# What the workflow keeps in the archive beside the changes: the guidance reviews'
# period ledger.
ARCHIVE_FILES = frozenset({"guidance-reviews.jsonl"})
# The outcome schema the engine checks every step's last turn against. The engine's
# command is `change-workflow` on the path, which names no path of the repository's,
# and a skill cites the engine's behaviour by requirement id, never its package.
ENGINE = frozenset({".agents/change-outcome.schema.json"})

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


def _workflow(*arguments: str) -> str:
    """What the workflow's command prints, run in a checkout of its own holding no
    configuration, committed or local: the roles and the fragment are the
    distribution's, whatever a repository configures."""
    with tempfile.TemporaryDirectory() as checkout:
        subprocess.run(["git", "init", "-q", checkout], check=True)
        done = workflow_command.run(arguments, Path(checkout))
    assert done.returncode == 0, done.stderr
    return done.stdout


@functools.cache
def workflow_roles() -> tuple[str, ...]:
    """Each role the workflow leaves to an adopting repository, by name, as `config
    --json` lists them."""
    return tuple(role["role"] for role in json.loads(_workflow("config", "--json"))["roles"])


@functools.cache
def fragment() -> Path:
    """The distribution's make fragment, at the path `fragment` prints."""
    return Path(_workflow("fragment").strip())


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


def _named(sources: list[tuple[str, list[str]]], root: Root) -> dict[str, set[str]]:
    where: dict[str, set[str]] = defaultdict(set)
    for name, texts in sources:
        for code in texts:
            for found in (*make_targets(code), *paths(code, root)):
                where[found].add(name)
    return where


def skill_names(root: Root, skills: Path = SKILLS) -> dict[str, set[str]]:
    """Every make target and repository path the workflow's skills name, each with the
    skills naming it."""
    return _named([(_shown(skill), code_of(skill.read_text("utf-8")))
                   for skill in sorted(path for pattern in WORKFLOW_SKILLS
                                       for path in skills.glob(pattern))], root)


def fragment_targets(path: Path) -> frozenset[str]:
    """The targets the make fragment at `path` defines."""
    return frozenset(rule["target"] for rule in _RULE.finditer(path.read_text("utf-8")))


def _openspec(path: str) -> bool:
    """OpenSpec's trees, the change index, the archive and what the workflow keeps in
    it, and anything in them named by a placeholder; never one change or capability by
    its name, nor the repository's capability index."""
    tree = next((tree for tree in OPENSPEC if path.startswith(tree)), None)
    if tree is None:
        return False
    if path == CHANGE_INDEX:
        return True
    segments = path[len(tree):].split("/")
    if tree == "openspec/changes/" and segments[0] == ARCHIVE:
        segments = segments[1:] or [""]
        if segments[0] in ARCHIVE_FILES:
            return True
    return segments[0] == "" or "<" in segments[0]


def workflows_own(name: str, targets: frozenset[str]) -> bool:
    """Whether `name`, a make target or a repository path, is the workflow's own: a
    target the fragment defines, run here or in a checkout `-C` names by a placeholder
    — another clone, a proposal's worktree — or a path the workflow holds."""
    if name.startswith("make "):
        words = name.split()
        return words[-1] in targets and (len(words) == 2 or "<" in words[2])
    return name in ENGINE or _openspec(name)


def exemptions(markdown: str) -> dict[str, str]:
    """The targets and paths a skill may name though they are no workflow's own, each
    with the change that owns its removal: the first table under the exemptions'
    heading, a name in code in its first cell and the change in its second."""
    tables = _tables(section(markdown, EXEMPTIONS_HEADING))
    found: dict[str, str] = {}
    for row in tables[0] if tables else []:
        owners = [match[2] for match in _SPAN.finditer(row[1])] if len(row) > 1 else []
        for match in _SPAN.finditer(row[0]):
            found[" ".join(match[2].split())] = owners[0] if owners else ""
    return found


def not_the_workflows(where: dict[str, set[str]], targets: frozenset[str],
                      exempted: dict[str, str]) -> list[str]:
    """Each name in `where` that is neither the workflow's own nor exempted, with the
    skills naming it."""
    return [f"{name} (named in {', '.join(sorted(where[name]))})" for name in sorted(where)
            if not workflows_own(name, targets) and name not in exempted]


def collected(root: Root, path: Path) -> dict[str, set[str]]:
    """Every make target and repository path the fragment at `path` names, the
    targets it defines among them, each with where it is named."""
    text = path.read_text("utf-8")
    where = _named([(_shown(path), text.splitlines())], root)
    for target in fragment_targets(path):
        where[f"make {target}"].add(_shown(path))
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
    """The roles a statement gives under `heading`: its first table's first cells."""
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
    OpenSpec command, the validation preflight's, and each evidence kind's `run`,
    `start`, `collect`, and `cleanup`, each a command or a list of them."""
    def each(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        return [command for command in value if isinstance(command, str)] \
            if isinstance(value, list) else []

    configuration = tomllib.loads(text)
    validation = configuration.get("validation", {})
    commands = [command for value in configuration.get("hooks", {}).values()
                for command in each(value)]
    commands += each(configuration.get("openspec", {}).get("command"))
    commands += each(validation.get("preflight"))
    for kind in validation.get("evidence", {}).values():
        for key in ("run", "start", "collect", "cleanup"):
            commands += each(kind.get(key))
    listed: set[str] = set()
    for command in commands:
        listed.update(make_targets(command))
        listed.update(paths(command, root))
    return listed


def guidance_directories(markdown: str, heading: str, root: Root) -> tuple[str, ...]:
    """The directories the provision of the guidance documents every step reads names,
    each written with its trailing `/`. Every Markdown file beneath one is such a
    document, as every Markdown file beneath a directory entry of the configuration's
    `[load]` is one a step loads; a directory another provision names provides only
    itself."""
    for table in _tables(section(markdown, heading)):
        for row in table:
            if row[0] == GUIDANCE_ROLE:
                return tuple(sorted(
                    path for match in (m for cell in row[1:] for m in _SPAN.finditer(cell))
                    for path in paths(match[2], root) if path.endswith("/")))
    return ()


def unlisted(where: dict[str, set[str]], listed: set[str],
             directories: tuple[str, ...] = ()) -> list[str]:
    """Each name in `where` that `listed` does not provide, with where it is named; a
    Markdown file beneath one of `directories` is provided."""
    return [f"{name} (named in {', '.join(sorted(where[name]))})"
            for name in sorted(set(where) - listed)
            if not (name.endswith(".md") and name.startswith(directories))]


def role_problems(stated: tuple[str, ...], here: str) -> list[str]:
    """Each role the workflow lists that this repository provides no way to fill,
    and each provision for a role the workflow does not list."""
    provided_for = roles(here, PROVISIONS_HEADING)
    if not stated:
        return ["the workflow lists no role"]
    return ([f"no provision for the role {role!r}" for role in stated
             if role not in provided_for]
            + [f"a provision for {role!r}, which the workflow lists no role for"
               for role in provided_for if role not in stated])


def listed_here(root: Root) -> set[str]:
    """What this repository provides: its statement's tables and its configuration's
    commands."""
    return (provided(PROVISIONS.read_text("utf-8"), PROVISIONS_HEADING, root)
            | configured(CONFIGURATION.read_text("utf-8"), root))


def test_every_target_and_path_a_skill_names_is_the_workflows_own() -> None:
    foreign = not_the_workflows(skill_names(tracked_root()), fragment_targets(fragment()),
                                exemptions(PROVISIONS.read_text("utf-8")))

    assert not foreign, "a workflow skill names a target or path that is not the " \
                        "workflow's own; name it by its role:\n" + "\n".join(foreign)


def test_every_exemption_is_named_by_a_skill_and_owned_by_an_open_change() -> None:
    """An exemption goes with what it exempts: once no skill names it, or once the
    change owning its removal is archived, which moves its directory away."""
    exempted, named = exemptions(PROVISIONS.read_text("utf-8")), skill_names(tracked_root())

    # None need stand: the section then holds no table, and the skills name only the
    # workflow's own, which the test above checks.
    assert [name for name in exempted if name not in named] == []
    assert [f"{name}: {owner or 'no owner'}" for name, owner in exempted.items()
            if not owner or not (ROOT / "openspec/changes" / owner).is_dir()] == []


def test_every_target_and_path_the_fragment_names_is_provided_here() -> None:
    root = tracked_root()

    missing = unlisted(collected(root, fragment()), listed_here(root),
                       guidance_directories(PROVISIONS.read_text("utf-8"),
                                            PROVISIONS_HEADING, root))

    assert not missing, "this repository's provision of the workflow's roles does not " \
                        "list:\n" + "\n".join(missing)


def test_each_role_has_a_provision_and_each_provision_a_role() -> None:
    problems = role_problems(workflow_roles(), PROVISIONS.read_text("utf-8"))

    assert not problems, "\n".join(problems)


def test_the_roles_and_the_fragment_are_the_distributions() -> None:
    """Library integration: the workflow's command, run as a process in a checkout
    with no configuration, lists its roles and prints its fragment's path."""
    assert len(workflow_roles()) == len(set(workflow_roles())) > 0
    assert fragment().name == "workflow.mk" and fragment().is_file()


# The collection itself, on texts and trees of the test's own.

ROOT_OF_TEST = Root(frozenset({"openspec", "docs", ".agents", ".claude", "helm", "scripts"}),
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
    assert paths("openspec/README.md#this-repositorys-closeout-parts, notes.md:57",
                 ROOT_OF_TEST) == ["openspec/README.md"]
    assert paths("Edit(docs/**)", ROOT_OF_TEST) == ["docs/**"]
    assert paths(".agents/change-outcome.schema.json AGENTS.md.", ROOT_OF_TEST) == [
        ".agents/change-outcome.schema.json", "AGENTS.md"]
    assert paths("README.md reviews/ ../*-proposal/** openspec validate helm",
                 ROOT_OF_TEST) == []


def _skill(tmp_path: Path, text: str) -> dict[str, set[str]]:
    (tmp_path / "skills/change-extra").mkdir(parents=True)
    (tmp_path / "skills/change-extra/SKILL.md").write_text(text, "utf-8")
    return skill_names(ROOT_OF_TEST, tmp_path / "skills")


def _sources(tmp_path: Path, fragment: str) -> dict[str, set[str]]:
    (tmp_path / "workflow.mk").write_text(fragment, "utf-8")
    return collected(ROOT_OF_TEST, tmp_path / "workflow.mk")


FRAGMENT_OF_TEST = frozenset({"validate", "check-change-index"})


def _shown_names(foreign: list[str]) -> list[str]:
    return [line.split(" (named in ")[0] for line in foreign]


def test_a_skill_naming_a_repositorys_check_is_named(tmp_path: Path) -> None:
    """CW-n8tr's "A skill names a repository's check" and CW-m4ps's "A skill names a
    new target": refused whether this repository's statement lists the target, its
    configuration's commands alone name it, or nothing does."""
    root = tracked_root()
    assert "make check-comment-hygiene" in provided(PROVISIONS.read_text("utf-8"),
                                                    PROVISIONS_HEADING, root)
    assert "make check-uv-version" in configured(CONFIGURATION.read_text("utf-8"), root)
    where = _skill(tmp_path, "Run `make check-comment-hygiene`, then `make check-something`, "
                             "then `make check-uv-version`.\n")

    foreign = not_the_workflows(where, FRAGMENT_OF_TEST, {})

    skill = tmp_path / "skills/change-extra/SKILL.md"
    assert foreign == [f"make check-comment-hygiene (named in {skill})",
                       f"make check-something (named in {skill})",
                       f"make check-uv-version (named in {skill})"]


def test_a_skill_may_name_the_workflows_own_targets_and_paths(tmp_path: Path) -> None:
    where = _skill(tmp_path, (
        "Run `make validate CHANGE=<change>`, `make -C <clone> validate`, and "
        "`make -C ../<x>-proposal check-change-index`; read "
        "`openspec/changes/README.md`, `openspec/changes/archive/<date>-<change>/`, "
        "`openspec/changes/archive/guidance-reviews.jsonl`, and "
        "`openspec/specs/<capability>/spec.md`; run `change-workflow next <change>`; "
        "match `.agents/change-outcome.schema.json`.\n"))

    assert {"make validate", "make -C <clone> validate",
            "openspec/specs/<capability>/spec.md"} <= set(where)
    assert not_the_workflows(where, FRAGMENT_OF_TEST, {}) == []


def test_a_skill_naming_a_repositorys_paths_is_named(tmp_path: Path) -> None:
    """The repository's own documents and its changes and capabilities by name, even in
    OpenSpec's directories, are not the workflow's; nor is a fragment target run in one
    of the repository's own directories."""
    where = _skill(tmp_path, (
        "Read `AGENTS.md`, `openspec/README.md#documentation-placement`, "
        "`openspec/specs/README.md`, `openspec/specs/change-workflow/spec.md`, "
        "`openspec/changes/some-change/notes.md`, "
        "`openspec/changes/archive/2026-01-01-x/notes.md`, "
        "`docs/development/ARCHITECTURE.md`, `docs/guidance/repository/README.md`, and "
        "`.agents/evidence/helm.md`; run `make -C helm validate`.\n"))

    assert _shown_names(not_the_workflows(where, FRAGMENT_OF_TEST, {})) == [
        ".agents/evidence/helm.md", "AGENTS.md", "docs/development/ARCHITECTURE.md",
        "docs/guidance/repository/README.md", "make -C helm validate",
        "openspec/README.md", "openspec/changes/archive/2026-01-01-x/notes.md",
        "openspec/changes/some-change/notes.md", "openspec/specs/README.md",
        "openspec/specs/change-workflow/spec.md"]


def test_a_skill_names_an_engineering_guidance_file(tmp_path: Path) -> None:
    """CW-n8tr's "A skill names an engineering guidance file": a skill cites the
    engineering guidance and the workflow's by section name, so a path into either
    fails, naming it, as does the engine's package."""
    where = _skill(tmp_path, (
        "Read `docs/guidance/engineering/test-levels.md`, "
        "`docs/guidance/workflow/closeout.md#archival`, and `docs/guidance/engineering/`, "
        "as `scripts/change_workflow/next_step.py` computes it.\n"))

    assert _shown_names(not_the_workflows(where, FRAGMENT_OF_TEST, {})) == [
        "docs/guidance/engineering/", "docs/guidance/engineering/test-levels.md",
        "docs/guidance/workflow/closeout.md", "scripts/change_workflow/next_step.py"]


def test_no_skill_names_a_guidance_file_by_its_name() -> None:
    """CW-7x0z: a skill cites guidance by section name, never by a file's name, which
    holds a user's guidance to this repository's files: no code span of a workflow
    skill is the bare name of a guidance file, its anchor or none."""
    guidance = {path.name for path in (ROOT / "docs/guidance").rglob("*.md")} - {"README.md"}
    named = [f"{path.parent.name}: {span}"
             for path in sorted(path for pattern in WORKFLOW_SKILLS
                                for path in SKILLS.glob(pattern))
             for match in _SPAN.finditer(path.read_text("utf-8"))
             if (span := " ".join(match[2].split())).split("#")[0] in guidance]

    assert named == []


def test_a_skill_naming_the_in_tree_command_is_named(tmp_path: Path) -> None:
    """A skill calls the installed command, `change-workflow`, never a copy of the
    engine a repository's tree holds."""
    where = _skill(tmp_path, "Run `scripts/change-workflow next <change>`.\n")

    assert _shown_names(not_the_workflows(where, FRAGMENT_OF_TEST, {})) == [
        "scripts/change-workflow"]


def test_an_exempted_name_is_admitted(tmp_path: Path) -> None:
    exempted = exemptions(f"## {EXEMPTIONS_HEADING}\n\n| Named in a skill | Owned by |\n"
                          "|---|---|\n| `make -C <package> test` | `some-change` |\n"
                          "| `.claude/` and `.claude/settings.json` | `some-change` |\n")
    where = _skill(tmp_path, "Run `make -C <package> test`, then `make -C <package> lint`; "
                             "an edit under `.claude/` is the orchestrator's.\n")

    assert exempted == {"make -C <package> test": "some-change", ".claude/": "some-change",
                        ".claude/settings.json": "some-change"}
    assert _shown_names(not_the_workflows(where, FRAGMENT_OF_TEST, exempted)) == [
        "make -C <package> lint"]


def test_only_the_guidance_provisions_directories_provide_what_lies_beneath() -> None:
    here = ("## How this repository provides the workflow's roles\n\n"
            "| Role | Provided by |\n|---|---|\n"
            "| The guidance documents every step reads | `AGENTS.md` and `docs/guidance/` |\n"
            "| Where documentation lives | `docs/` and `openspec/` |\n")
    where = {name: {"a skill"} for name in (
        "docs/guidance/engineering/test-levels.md", "docs/guidance/engineering/x.toml",
        "docs/guidance-other.md", "docs/development/TESTING.md")}

    directories = guidance_directories(here, PROVISIONS_HEADING, ROOT_OF_TEST)

    assert directories == ("docs/guidance/",)
    assert unlisted(where, provided(here, PROVISIONS_HEADING, ROOT_OF_TEST), directories) == [
        "docs/development/TESTING.md (named in a skill)",
        "docs/guidance-other.md (named in a skill)",
        "docs/guidance/engineering/x.toml (named in a skill)"]


def test_the_guidance_review_is_read_and_openspecs_own_skills_are_not(tmp_path: Path) -> None:
    for name, text in (("guidance-review", "Append to `openspec/changes/archive/x.jsonl`.\n"),
                       ("openspec-propose", "Run `make check-something`.\n")):
        (tmp_path / "skills" / name).mkdir(parents=True)
        (tmp_path / "skills" / name / "SKILL.md").write_text(text, "utf-8")

    where = skill_names(ROOT_OF_TEST, tmp_path / "skills")

    assert set(where) == {"openspec/changes/archive/x.jsonl"}


def test_the_fragment_names_its_targets_and_paths(tmp_path: Path) -> None:
    where = _sources(
        tmp_path,
        "# Included by a repository's Makefile.\nCHANGE_WORKFLOW ?= x\n"
        "design: ## A step\n\t@$(CHANGE_WORKFLOW) start design\n"
        "lock-all:\n\tmake lock && cat openspec/README.md\n")

    assert set(where) == {"make lock", "openspec/README.md", "Makefile", "make design",
                          "make lock-all"}
    assert where["make design"] == {str(tmp_path / "workflow.mk")}


def test_the_configurations_commands_are_provisions() -> None:
    """A hook's commands, the preflight's, and each evidence kind's are what the
    configuration provides; a document it loads, a guide, or a pattern is not a
    command."""
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
[validation.evidence.helm]
required = "always"
run = "make validate-helm CHANGE={change}"
evidence = ".snapshot/evidence/{tree}/helm/*/summary.json"
guide = ".agents/evidence/helm.md"
cleanup = ["make -C helm teardown CHANGE={change}"]
"""

    assert configured(text, ROOT_OF_TEST) == {
        "make check-repository", "make test", "make check-packaging",
        "make check-uv-version", "make validate-helm", "make -C helm teardown"}


def test_the_workflow_adds_a_role() -> None:
    """MCW-5tgp's "The workflow adds a role", as a unit of the comparison: a role the
    workflow lists, given here as `config --json` would list it, that this
    repository's statement does not name fails it, naming the role."""
    here = "## How this repository provides the workflow's roles\n\n| Role | Provided by |\n" \
           "|---|---|\n| A role | `make x` |\n| A third role | `make y` |\n"

    assert role_problems(("A role", "Another role"), here) == [
        "no provision for the role 'Another role'",
        "a provision for 'A third role', which the workflow lists no role for"]
