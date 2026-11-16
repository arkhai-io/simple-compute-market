"""The guidance check holds every guidance file to the layer model: one layer tag,
tags its layer's vocabulary or a lower one's defines, every vocabulary row carried,
well-formed tables, no link to a higher layer, and every cited anchor a heading."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from check_guidance import anchors, check, frontmatter_tags, main, repository_files, slug

ENGINEERING_README = """---
tags: [engineering]
---

# Engineering guidance

## Tags

| Tag | Kind | Description |
|---|---|---|
| `engineering` | layer | Holds without the workflow |
| `testing` | topic | Tests |
"""

TESTING = """---
tags: [engineering, testing]
---

# Testing

## Levels

A test proves what its level can.
"""

WORKFLOW_README = """---
tags: [workflow]
---

# The workflow's guidance

## Tags

| Tag | Kind | Description |
|---|---|---|
| `workflow` | layer | Holds in any repository adopting the workflow |
| `closeout` | topic | The closeout task |
"""

CLOSEOUT = """---
tags: [workflow, closeout]
---

# Closeout

## Archival

Tests prove completion as [`testing.md`, "Levels"](../engineering/testing.md#levels) says.
"""

AGENTS = """---
tags: [repository]
---

# Repository engineering guidance

## Where the guidance lives

| Layer | Guidance |
|---|---|
| engineering | [`docs/guidance/engineering/`](docs/guidance/engineering/README.md) |
| workflow | [`docs/guidance/workflow/`](docs/guidance/workflow/README.md) |
| repository | `AGENTS.md` |
| repository | [`openspec/README.md`](openspec/README.md) |
| repository | [`docs/development/TESTING.md`](docs/development/TESTING.md) |

| Role | Here |
|---|---|
| The roadmap | [`docs/development/ROADMAP.md`](docs/development/ROADMAP.md) |

## Tags

| Tag | Kind | Description |
|---|---|---|
| `repository` | layer | Names this repository's packages |

## Exceptions to shared guidance

| Shared rule | Kind | Here | Reason |
|---|---|---|---|
| [`testing.md`, "Levels"](docs/guidance/engineering/testing.md#levels) | selects | The unit level | It is small |
"""

OPENSPEC_README = """---
tags: [repository]
---

# This repository's OpenSpec guide

## Packaging

Run the packaging checks.
"""

REPOSITORY_TESTING = """---
tags: [repository, testing]
---

# Testing here

The lanes follow [the levels](../guidance/engineering/testing.md#levels).
"""

POOL_TESTING = """---
tags: [repository, testing]
---

# Pool testing

## Offering modes
"""

ENGINEERING_TESTING = "docs/guidance/engineering/testing.md"
ENGINEERING_TABLE = "docs/guidance/engineering/README.md"
WORKFLOW_CLOSEOUT = "docs/guidance/workflow/closeout.md"
POOL = "openspec/specs/pool/testing.md"

TREE = {
    "AGENTS.md": AGENTS,
    "openspec/README.md": OPENSPEC_README,
    ENGINEERING_TABLE: ENGINEERING_README,
    ENGINEERING_TESTING: TESTING,
    "docs/guidance/workflow/README.md": WORKFLOW_README,
    WORKFLOW_CLOSEOUT: CLOSEOUT,
    "docs/development/TESTING.md": REPOSITORY_TESTING,
    "docs/development/ROADMAP.md": "# Roadmap\n",
    "openspec/specs/pool/spec.md": "# Pool\n",
    "openspec/specs/pool/architecture.md": "# Pool architecture\n",
    POOL: POOL_TESTING,
    "openspec/specs/flow/spec.md": "# Flow\n",
    "openspec/specs/flow/index.md": "# Flow index\n",
    "openspec/specs/flow/README.md": "# Flow companion\n",
    "openspec/changes/a-change/draft.md": "# Draft\n\n```markdown\n---\ntags: [x]\n---\n```\n",
}


def _tree(root: Path, changes: dict[str, str | None] | None = None) -> Path:
    """The passing tree, with each file `changes` names written as given, or left out
    when given None."""
    files = {**TREE, **(changes or {})}
    for path, text in files.items():
        if text is not None:
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text, "utf-8")
    return root


def _files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*.md"))


def _problems(root: Path) -> list[str]:
    return check(root, _files(root)).problems


def _testing_tags(tags: str) -> dict[str, str | None]:
    return {ENGINEERING_TESTING: TESTING.replace("[engineering, testing]", tags)}


def test_the_passing_tree_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path)

    assert _problems(root) == []
    assert main([], root=root, lister=_files) == 0
    assert capsys.readouterr().out.startswith("OK: 8 guidance files are tagged")


def test_the_set_is_found_by_place_tags_and_the_layer_table(tmp_path: Path) -> None:
    """The guidance set: `docs/guidance/`; a capability's directory but its
    specification, its companion — `architecture.md`, or `README.md` beside an index —
    and its index; a tagged file outside the changes; and the documents the root
    guidance's layer table names — not one another of its tables names, nor a change's
    document however it is tagged."""
    tagged = "---\ntags: [repository]\n---\n# N\n"
    root = _tree(tmp_path, {"docs/notes/tagged.md": tagged,
                            "openspec/changes/a-change/summary.md": tagged,
                            "openspec/specs/plain/spec.md": "# Plain\n",
                            "openspec/specs/plain/README.md": tagged})

    assert sorted(check(root, _files(root)).tags) == [
        "AGENTS.md", "docs/development/TESTING.md", ENGINEERING_TABLE, ENGINEERING_TESTING,
        "docs/guidance/workflow/README.md", WORKFLOW_CLOSEOUT, "docs/notes/tagged.md",
        "openspec/README.md", "openspec/specs/plain/README.md", POOL]


def test_an_untagged_capability_guide(tmp_path: Path) -> None:
    """MCW-c4ek's scenario: found by its place, so failing rather than escaping."""
    root = _tree(tmp_path, {POOL: "# Pool testing\n"})

    assert _problems(root) == [
        f"{POOL}: has no tags in its frontmatter; a guidance file carries one layer tag, one "
        "of engineering, workflow, repository"]


def test_an_untagged_architecture_md_beside_an_index(tmp_path: Path) -> None:
    """Beside an index the companion is `README.md`, so `architecture.md` is guidance
    found by its place, and fails untagged."""
    architecture = "openspec/specs/flow/architecture.md"
    root = _tree(tmp_path, {architecture: "# Flow architecture\n"})

    assert _problems(root) == [
        f"{architecture}: has no tags in its frontmatter; a guidance file carries one layer "
        "tag, one of engineering, workflow, repository"]


def test_a_file_with_no_layer_tag(tmp_path: Path) -> None:
    """CW-g7lt's scenario "A file states no layer"."""
    root = _tree(tmp_path, _testing_tags("[testing]"))

    assert any(problem.startswith(f"{ENGINEERING_TESTING}: carries no layer tag")
               for problem in _problems(root))


def test_a_file_with_several_layer_tags(tmp_path: Path) -> None:
    root = _tree(tmp_path, _testing_tags("[engineering, workflow, testing]"))

    assert (f"{ENGINEERING_TESTING}: carries several layer tags, engineering, workflow; a "
            "guidance file carries one") in _problems(root)


def test_a_tag_no_vocabulary_defines(tmp_path: Path) -> None:
    root = _tree(tmp_path, _testing_tags("[engineering, testing, nonsense]"))

    assert _problems(root) == [
        f"{ENGINEERING_TESTING}: carries the tag nonsense, which neither the engineering "
        "vocabulary nor a lower layer's defines"]


def test_a_tag_only_a_higher_layer_defines(tmp_path: Path) -> None:
    root = _tree(tmp_path, _testing_tags("[engineering, testing, closeout]"))

    assert _problems(root) == [
        f"{ENGINEERING_TESTING}: carries the tag closeout, which only the workflow "
        "vocabulary, a higher layer's, defines"]


def test_a_lower_layers_tag_is_allowed(tmp_path: Path) -> None:
    """The repository's testing documents carry `testing`, an engineering tag."""
    assert _problems(_tree(tmp_path)) == []


def test_a_layer_no_vocabulary_defines(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"docs/guidance/workflow/README.md": WORKFLOW_README.split(
        "## Tags")[0], WORKFLOW_CLOSEOUT: CLOSEOUT.replace("[workflow, closeout]", "[workflow]")})

    assert _problems(root) == [
        "docs/guidance/workflow/README.md: carries the layer tag workflow, which no "
        "vocabulary table defines",
        f"{WORKFLOW_CLOSEOUT}: carries the layer tag workflow, which no vocabulary table "
        "defines"]


def test_a_vocabulary_row_no_file_carries(tmp_path: Path) -> None:
    root = _tree(tmp_path, {ENGINEERING_TABLE: ENGINEERING_README
                            + "| `python` | tool | The Python language |\n"})

    assert _problems(root) == [
        f"{ENGINEERING_TABLE}: the engineering vocabulary's tag python is carried by no "
        "guidance file"]


@pytest.mark.parametrize("table,why", [
    ("| Tag | Kind |\n|---|---|\n| `engineering` | layer |\n", "its header is | Tag | Kind |"),
    ("| Tag | Kind | Description |\n| `engineering` | layer | x |\n",
     "its second line is no delimiter row"),
    ("| Tag | Kind | Description |\n|---|---|---|\n| `engineering` | layer |\n",
     "has 2 cells, not 3"),
    ("| Tag | Kind | Description |\n|---|---|---|\n| engineering | layer | x |\n",
     "needs a tag in backticks"),
    ("| Tag | Kind | Description |\n|---|---|---|\n| `testing` | topic | x |\n"
     "| `engineering` | layer | x |\n", "its first row must be a layer tag"),
    ("| Tag | Kind | Description |\n|---|---|---|\n| `engineering` | layer | x |\n"
     "| `testing` | topic | x |\n| `testing` | topic | y |\n", "it defines testing twice"),
    ("| Tag | Kind | Description |\n|---|---|---|\n| `engineering` | layer | x |\n"
     "| `testing` | layer | x |\n", "only its first row is a layer tag"),
    ("Nothing tabled here.\n", "holds no table"),
])
def test_a_malformed_vocabulary_table(tmp_path: Path, table: str, why: str) -> None:
    root = _tree(tmp_path, {ENGINEERING_TABLE: ENGINEERING_README.split("| Tag |")[0] + table})

    problems = _problems(root)

    assert any(problem.startswith(f"{ENGINEERING_TABLE}:") and "is malformed" in problem
               and why in problem for problem in problems), problems


def test_a_second_vocabulary_of_one_layer(tmp_path: Path) -> None:
    root = _tree(tmp_path, {ENGINEERING_TESTING: TESTING + (
        "\n## Tags\n\n| Tag | Kind | Description |\n|---|---|---|\n"
        "| `engineering` | layer | again |\n")})

    assert any("is a second vocabulary of the engineering layer" in problem
               for problem in _problems(root))


def test_an_exception_row_citing_no_guidance_file(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"AGENTS.md": AGENTS.replace(
        "[`testing.md`, \"Levels\"](docs/guidance/engineering/testing.md#levels)",
        "[the roadmap](docs/development/ROADMAP.md)")})

    assert any("an exception row cites no guidance file: [the roadmap]" in problem
               for problem in _problems(root))


def test_an_exception_row_naming_an_unknown_kind(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"AGENTS.md": AGENTS.replace("| selects |", "| waives |")})

    assert any("an exception row names the kind 'waives', not selects or overrides" in problem
               for problem in _problems(root))


def test_a_malformed_exception_table(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"AGENTS.md": AGENTS.replace(
        "| Shared rule | Kind | Here | Reason |", "| Rule | Kind | Here | Reason |")})

    assert any(problem.startswith("AGENTS.md:") and "Exceptions to shared guidance" in problem
               and "is malformed" in problem for problem in _problems(root))


def test_engineering_guidance_links_upward(tmp_path: Path) -> None:
    """MCW-c4ek's scenario: naming both files."""
    root = _tree(tmp_path, {ENGINEERING_TESTING: TESTING
                            + "\nAs [the root guidance](../../../AGENTS.md) says.\n"})

    assert _problems(root) == [
        f"{ENGINEERING_TESTING}:11: links to AGENTS.md, a guidance file tagged repository, "
        "from a file tagged engineering, a lower layer"]


def test_workflow_guidance_links_to_a_repository_document(tmp_path: Path) -> None:
    """CW-d2rw's scenario."""
    root = _tree(tmp_path, {WORKFLOW_CLOSEOUT: CLOSEOUT
                            + "\nRun [the packaging part](../../../openspec/README.md#packaging).\n"})

    assert any(problem.startswith(f"{WORKFLOW_CLOSEOUT}:11: links to openspec/README.md, a "
                                  "guidance file tagged repository")
               for problem in _problems(root))


def test_a_link_inside_code_is_no_link(tmp_path: Path) -> None:
    root = _tree(tmp_path, {ENGINEERING_TESTING: TESTING + (
        "\n`[root](../../../AGENTS.md)`\n\n```\n[root](../../../AGENTS.md)\n```\n")})

    assert _problems(root) == []


def test_a_guidance_links_section_moved(tmp_path: Path) -> None:
    """MCW-c4ek's scenario: a skill's link whose anchor names no heading, named with
    its anchor."""
    root = _tree(tmp_path, {".agents/skills/close/SKILL.md": (
        "---\nname: close\n---\n\nFollow [the packaging part]"
        "(../../../openspec/README.md#moved-section).\n")})

    assert _problems(root) == [
        ".agents/skills/close/SKILL.md:5: cites openspec/README.md#moved-section, and no "
        "heading of openspec/README.md has that anchor"]


def test_a_quoted_path_whose_anchor_names_no_heading(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"openspec/changes/a-change/notes.md": (
        f"# Tasks\n\nAs `{WORKFLOW_CLOSEOUT}#archival` and \"{WORKFLOW_CLOSEOUT}#gone\" say.\n")})

    assert _problems(root) == [
        f"openspec/changes/a-change/notes.md:3: cites {WORKFLOW_CLOSEOUT}#gone, and no heading "
        f"of {WORKFLOW_CLOSEOUT} has that anchor"]


def test_an_anchor_alone_cites_its_own_file(tmp_path: Path) -> None:
    root = _tree(tmp_path, {ENGINEERING_TESTING: TESTING
                            + "\nSee [levels](#levels) and [nothing](#nothing).\n"})

    assert _problems(root) == [
        f"{ENGINEERING_TESTING}:11: cites {ENGINEERING_TESTING}#nothing, and no heading of "
        f"{ENGINEERING_TESTING} has that anchor"]


def test_a_citation_of_a_file_outside_the_guidance_is_not_checked(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"docs/handbook.md": "# Handbook\n\n[r](development/ROADMAP.md#x)\n"})

    assert _problems(root) == []


def test_the_archive_and_the_prompts_keep_their_citations(tmp_path: Path) -> None:
    stale = f"# Old\n\nAs `{WORKFLOW_CLOSEOUT}#gone` said.\n"
    root = _tree(tmp_path, {"openspec/changes/archive/2026-01-01-old/notes.md": stale,
                            "docs/prompts/plan.md": stale})

    assert _problems(root) == []


def test_a_workflow_file_under_the_engineering_directory_passes(tmp_path: Path) -> None:
    """CW-n6dm's scenario: no layer is read from a directory."""
    root = _tree(tmp_path, {"docs/guidance/engineering/review.md": (
        "---\ntags: [workflow, closeout]\n---\n\n# Review\n\n"
        "[Archival](../workflow/closeout.md#archival)\n")})

    assert _problems(root) == []


def test_a_block_list_of_tags_is_read() -> None:
    assert frontmatter_tags("---\ntags:\n  - engineering\n  - testing\n---\n# T\n") == [
        "engineering", "testing"]
    assert frontmatter_tags("# No frontmatter\n") is None
    assert frontmatter_tags("---\nname: x\n---\n") is None


def test_tags_that_are_no_list_are_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path, _testing_tags("engineering"))

    assert any(problem.startswith(f"{ENGINEERING_TESTING}: its frontmatter's tags must be a "
                                  "list") for problem in _problems(root))


def test_a_layer_table_document_that_does_not_exist(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"docs/development/TESTING.md": None})

    assert any(problem.startswith("AGENTS.md:") and "names docs/development/TESTING.md, which "
               "does not exist" in problem for problem in _problems(root))


@pytest.mark.parametrize("heading,anchor", [
    ("This repository's closeout parts", "this-repositorys-closeout-parts"),
    ("`[cache]` directory entries", "cache-directory-entries"),
    ("Step 4 — `[cache]` may name a directory", "step-4--cache-may-name-a-directory"),
    ("Requirement: AB-x1yz A step's documents come from the configuration",
     "requirement-ab-x1yz-a-steps-documents-come-from-the-configuration"),
    ("[The companion](README.md), its *limits*", "the-companion-its-limits"),
    ("snake_case names", "snake_case-names"),
    ("The _current_ system, **in short**", "the-current-system-in-short"),
    ("`config load <step>` and <em>more</em>", "config-load-step-and-more"),
    ("`snake_case` in code", "snake_case-in-code"),
])
def test_headings_are_slugged_as_github_renders_them(heading: str, anchor: str) -> None:
    assert slug(heading) == anchor


def test_a_repeated_heading_is_numbered_and_code_holds_no_heading() -> None:
    text = ("---\ntags: [x]\n---\n# Notes\n\n## Notes\n\n```markdown\n## Fenced\n"
            "```python\n## Still fenced: an info string closes nothing\n```\n\n"
            "- A list item:\n\n    ```text\n    ## Indented fence\n    ```\n\n"
            "## Closing ##\n\n<a id=\"kept\"></a> <span id=\"spanned\"></span>\n")

    assert anchors(text) == {"notes", "notes-1", "closing", "kept", "spanned"}


def test_the_listing_prints_each_guidance_file_with_its_tags(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path)

    assert main(["--list"], root=root, lister=_files) == 0
    listed = capsys.readouterr().out.splitlines()
    assert "AGENTS.md: repository" in listed
    assert f"{POOL}: repository, testing" in listed
    assert len(listed) == 8

    assert main(["--list", "--tag", "testing"], root=root, lister=_files) == 0
    assert capsys.readouterr().out.splitlines() == [
        "docs/development/TESTING.md: repository, testing",
        f"{ENGINEERING_TESTING}: engineering, testing",
        f"{POOL}: repository, testing"]


def test_the_listing_of_exceptions_prints_every_row(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-x4ex's scenario "One capability departs from a shared rule": the row beside
    the capability is listed with the root guidance's."""
    root = _tree(tmp_path, {POOL: POOL_TESTING + (
        "\n## Exceptions to shared guidance\n\n| Shared rule | Kind | Here | Reason |\n"
        "|---|---|---|---|\n| [`testing.md`](../../../docs/guidance/engineering/testing.md) "
        "| overrides | The pool's tests patch | No seam yet |\n")})

    assert main(["--list-exceptions"], root=root, lister=_files) == 0

    assert capsys.readouterr().out.splitlines() == [
        "AGENTS.md: selects: [`testing.md`, \"Levels\"](docs/guidance/engineering/testing.md"
        "#levels) — The unit level",
        f"{POOL}: overrides: [`testing.md`](../../../docs/guidance/engineering/testing.md) — "
        "The pool's tests patch"]


def test_a_failing_tree_fails_naming_each_problem(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path, {POOL: "# Pool testing\n"})

    assert main([], root=root, lister=_files) == 1

    out = capsys.readouterr().out
    assert out.startswith(f"{POOL}: has no tags")
    assert "FAIL: 1 problem(s) in the guidance" in out


def test_tag_needs_the_listing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--tag", "testing"], root=_tree(tmp_path), lister=_files)


def test_the_files_are_those_git_tracks_or_would_track(tmp_path: Path) -> None:
    """A guide written and not yet added is checked; an ignored file is not one."""
    root = _tree(tmp_path)
    (root / ".gitignore").write_text("ignored/\n", "utf-8")
    (root / "ignored").mkdir()
    (root / "ignored/notes.md").write_text("# Ignored\n", "utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "AGENTS.md"], cwd=root, check=True)

    listed = repository_files(root)

    assert "AGENTS.md" in listed and POOL in listed
    assert "ignored/notes.md" not in listed
    assert listed == sorted(set(_files(root)) - {"ignored/notes.md"})
