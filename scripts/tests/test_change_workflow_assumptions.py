"""Every make target and repository path the workflow's skills name is the workflow's
own; every one its step table and its make fragment name is one this repository says
it provides; and each role the workflow asks of an adopting repository has a provision
here.

A skill is shared by every repository that adopts the workflow, so it names no
repository's target or path (CW-n8tr): only the workflow's own — its guidance and the
engineering guidance it rests on, OpenSpec's tree as the workflow knows it, the
engine's command and package and the outcome schema it reads, and the make fragment's
targets — or one this repository's table of exemptions lists, each owned by the open
change that removes it. What a repository does not hold in common reaches a skill
through its configuration and its guides, never through the skill's text.

The step table and the make fragment are this repository's. The roles are
stated twice: in `change-workflow`'s `README.md`, what any adopting repository
provides, and in `market-change-workflow`'s, how this one provides each. This
repository provides them in two places: its workflow configuration,
`.agents/workflow.toml`, whose hooks' and evidence kinds' commands are provisions as
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
the documents but not collected, since whether it exists depends on the checkout. A
directory the provision of the guidance documents every step reads names, written
with its trailing `/`, provides every Markdown file beneath it; a directory any other
provision names provides only itself.
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
GUIDANCE_ROLE = "The guidance documents every step reads"
EXEMPTIONS_HEADING = "What the workflow's skills name of this repository"

# The guidance a skill may cite: the workflow's, and the engineering guidance below it,
# which the workflow's guidance links and so needs wherever the workflow goes. A file's
# frontmatter states its layer, wherever it sits (CW-n6dm).
GUIDANCE = ("docs/guidance/workflow/", "docs/guidance/engineering/")
GUIDANCE_LAYERS = frozenset({"workflow", "engineering"})
# OpenSpec's two trees as the workflow knows them: a change or a capability named by a
# placeholder, never by its name, beside the change index and the archive.
OPENSPEC = ("openspec/changes/", "openspec/specs/")
CHANGE_INDEX = "openspec/changes/README.md"
ARCHIVE = "archive"
# What the workflow keeps in the archive beside the changes: the guidance reviews'
# period ledger.
ARCHIVE_FILES = frozenset({"guidance-reviews.jsonl"})
# The engine's command and package, and the outcome schema it checks every step's last
# turn against.
ENGINE = frozenset({"scripts/change-workflow", ".agents/change-outcome.schema.json"})
ENGINE_PACKAGE = "scripts/change_workflow/"
_LAYER = re.compile(r"^tags:\s*\[([^\]]*)\]", re.M)

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


def fragment_targets(fragment: Path = FRAGMENT) -> frozenset[str]:
    """The targets the make fragment defines."""
    return frozenset(rule["target"] for rule in _RULE.finditer(fragment.read_text("utf-8")))


def _guidance(path: str) -> bool:
    """A guidance directory, or a file whose frontmatter's layer is the workflow's or
    the engineering guidance's."""
    if path in GUIDANCE:
        return True
    if not path.startswith("docs/guidance/") or not path.endswith(".md"):
        return False
    document = ROOT / path
    layer = _LAYER.search(document.read_text("utf-8")) if document.is_file() else None
    return layer is not None and bool(
        {tag.strip() for tag in layer[1].split(",")} & GUIDANCE_LAYERS)


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
    return (name in ENGINE or name.startswith(ENGINE_PACKAGE) or _guidance(name)
            or _openspec(name))


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


def collected(root: Root, step_table: Path = STEP_TABLE,
              fragment: Path = FRAGMENT) -> dict[str, set[str]]:
    """Every make target and repository path the step table and the fragment name, the
    targets the fragment defines among them, each with where it is named."""
    table = tomllib.loads(step_table.read_text("utf-8"))
    # A step's rules are under `[steps.<name>]`, the shared ones under `[common]`.
    rows = [table.get("common", {}), *table.get("steps", {}).values()]
    rules = [rule for row in rows for key in ("allow", "deny") for rule in row.get(key, [])]
    text = fragment.read_text("utf-8")
    where = _named([(_shown(step_table), rules), (_shown(fragment), text.splitlines())], root)
    for target in fragment_targets(fragment):
        where[f"make {target}"].add(_shown(fragment))
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
    validation preflight's, and each evidence kind's `run`, `start`, `collect`, and
    `cleanup`, each a command or a list of them."""
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


def test_every_target_and_path_a_skill_names_is_the_workflows_own() -> None:
    foreign = not_the_workflows(skill_names(tracked_root()), fragment_targets(),
                                exemptions(PROVISIONS.read_text("utf-8")))

    assert not foreign, "a workflow skill names a target or path that is not the " \
                        "workflow's own; name it by its role:\n" + "\n".join(foreign)


def test_every_exemption_is_named_by_a_skill_and_owned_by_an_open_change() -> None:
    """An exemption goes with what it exempts: once no skill names it, or once the
    change owning its removal is archived, which moves its directory away."""
    exempted, named = exemptions(PROVISIONS.read_text("utf-8")), skill_names(tracked_root())

    assert exempted
    assert [name for name in exempted if name not in named] == []
    assert [f"{name}: {owner or 'no owner'}" for name, owner in exempted.items()
            if not owner or not (ROOT / "openspec/changes" / owner).is_dir()] == []


def test_every_target_and_path_the_step_table_and_the_fragment_name_is_provided_here() -> None:
    root = tracked_root()

    missing = unlisted(collected(root), listed_here(root),
                       guidance_directories(PROVISIONS.read_text("utf-8"),
                                            PROVISIONS_HEADING, root))

    assert not missing, "this repository's provision of the workflow's roles does not " \
                        "list:\n" + "\n".join(missing)


def test_each_role_has_a_provision_and_each_provision_a_role() -> None:
    problems = role_problems(ROLES.read_text("utf-8"), PROVISIONS.read_text("utf-8"))

    assert not problems, "\n".join(problems)


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


def _sources(tmp_path: Path, table: str = "", fragment: str = "") -> dict[str, set[str]]:
    (tmp_path / "table.toml").write_text(table, "utf-8")
    (tmp_path / "workflow.mk").write_text(fragment, "utf-8")
    return collected(ROOT_OF_TEST, tmp_path / "table.toml", tmp_path / "workflow.mk")


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
        "`docs/guidance/workflow/closeout.md#archival`, `docs/guidance/engineering/comments.md`, "
        "`openspec/changes/README.md`, `openspec/changes/archive/<date>-<change>/`, "
        "`openspec/changes/archive/guidance-reviews.jsonl`, and "
        "`openspec/specs/<capability>/spec.md`; run `scripts/change-workflow next <change>`, "
        "as `scripts/change_workflow/next_step.py` computes it; match "
        "`.agents/change-outcome.schema.json`.\n"))

    assert {"make validate", "make -C <clone> validate", "scripts/change-workflow",
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


def test_an_exempted_name_is_admitted(tmp_path: Path) -> None:
    exempted = exemptions(f"## {EXEMPTIONS_HEADING}\n\n| Named in a skill | Owned by |\n"
                          "|---|---|\n| `make -C <package> test` | `some-change` |\n"
                          "| `.claude/` and `.claude/change-steps.toml` | `some-change` |\n")
    where = _skill(tmp_path, "Run `make -C <package> test`, then `make -C <package> lint`; "
                             "an edit under `.claude/` is the orchestrator's.\n")

    assert exempted == {"make -C <package> test": "some-change", ".claude/": "some-change",
                        ".claude/change-steps.toml": "some-change"}
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


def test_a_role_with_no_provision_is_named() -> None:
    general = "## What an adopting repository provides\n\n| Role | Used by |\n|---|---|\n" \
              "| A role | design |\n| Another role | plan |\n"
    here = "## How this repository provides the workflow's roles\n\n| Role | Provided by |\n" \
           "|---|---|\n| A role | `make x` |\n| A third role | `make y` |\n"

    assert role_problems(general, here) == [
        "no provision for the role 'Another role'",
        "a provision for 'A third role', which the workflow states no role for"]
