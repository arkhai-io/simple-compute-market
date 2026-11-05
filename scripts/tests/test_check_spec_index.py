"""An indexed capability's spec.md is held to its index.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from check_spec_index import capability_problems, main, problems, read_deltas, slug

CHANGE = "shape-bounds"
SPEC = """# example-flow Specification

## Purpose

The flow.

## Requirements

### Requirement: EF-a8tf The flow starts

It MUST start.

#### Scenario: Started

- **WHEN** it runs
- **THEN** it starts

### Requirement: EF-q4ze The flow ends

It MUST end.
"""
INDEX = """# example-flow

Prefix: `EF`

## 1. The flow

- [EF-a8tf](spec.md#requirement-ef-a8tf-the-flow-starts) — it starts.
- [EF-q4ze](spec.md#requirement-ef-q4ze-the-flow-ends) — it ends.

## Retired ids

- `EF-zz00` — its rule moved to EF-q4ze.
"""
ADDED = """## ADDED Requirements

### Requirement: EF-n3w1 The flow pauses

It MAY pause.

#### Scenario: Paused

- **WHEN** asked
- **THEN** it pauses
"""


def _capability(root: Path, spec: str = SPEC, index: str | None = INDEX,
                name: str = "example-flow") -> Path:
    capability = root / "openspec/specs" / name
    capability.mkdir(parents=True)
    (capability / "spec.md").write_text(spec, "utf-8")
    if index is not None:
        (capability / "index.md").write_text(index, "utf-8")
    return capability


def _delta(root: Path, text: str, name: str = "example-flow") -> None:
    delta = root / "openspec/changes" / CHANGE / "specs" / name / "spec.md"
    delta.parent.mkdir(parents=True)
    delta.write_text(text, "utf-8")


def test_an_index_agreeing_with_its_specification_passes(tmp_path: Path) -> None:
    _capability(tmp_path)

    assert problems(tmp_path) == []


def test_a_capability_without_an_index_is_not_checked(tmp_path: Path) -> None:
    _capability(tmp_path, spec=SPEC.replace("EF-a8tf ", ""), index=None)

    assert problems(tmp_path) == []


@pytest.mark.parametrize("spec,index,named", [
    (SPEC.replace("EF-a8tf ", ""), INDEX,
     "requirement 'The flow starts' begins with no id"),
    (SPEC.replace("EF-a8tf ", "ef-a8tf "), INDEX, "'ef-a8tf The flow starts' begins with no id"),
    (SPEC.replace("EF-a8tf ", "EF-a8t "), INDEX, "begins with no id"),
    (SPEC.replace("EF-q4ze", "EF-a8tf"), INDEX, "two requirements share the id EF-a8tf"),
    (SPEC, INDEX.replace("- [EF-q4ze]", "- see [EF-q4ze]"), "index.md does not list EF-q4ze"),
    (SPEC, INDEX.replace("## Retired ids", "- [EF-a8tf](spec.md#requirement-ef-a8tf-the-flow-"
                                           "starts) — again.\n\n## Retired ids"),
     "index.md lists EF-a8tf twice"),
    (SPEC, INDEX.replace("## Retired ids",
                         "- [EF-mmmm](spec.md) — gone.\n\n## Retired ids"),
     "index.md lists EF-mmmm, which neither spec.md nor the change's deltas hold"),
    (SPEC.replace("EF-q4ze", "EF-zz00"), INDEX.replace("EF-q4ze](spec.md#requirement-ef-q4ze",
                                                       "EF-zz00](spec.md#requirement-ef-zz00"),
     "the retired id EF-zz00 is in use"),
    (SPEC, INDEX.replace("#requirement-ef-q4ze-the-flow-ends", "#requirement-ef-q4ze-renamed"),
     "the link spec.md#requirement-ef-q4ze-renamed does not resolve: spec.md has no heading"),
    (SPEC, INDEX + "\nSee [the readme](README.md).\n",
     "the link README.md does not resolve: its file README.md does not exist"),
    (SPEC, INDEX.replace("Prefix: `EF`\n", ""), "declares no prefix"),
])
def test_each_disagreement_is_named(tmp_path: Path, spec: str, index: str,
                                    named: str) -> None:
    _capability(tmp_path, spec=spec, index=index)

    found = problems(tmp_path)

    assert any(named in problem for problem in found), found
    assert all(problem.startswith("example-flow: ") for problem in found)


def test_an_id_only_a_changes_added_delta_holds_is_accepted_from_it(tmp_path: Path) -> None:
    index = INDEX.replace("## Retired ids", "- [EF-n3w1](spec.md#requirement-ef-n3w1-the-flow-"
                                            "pauses) — it pauses.\n\n## Retired ids")
    _capability(tmp_path, index=index)
    _delta(tmp_path, ADDED)

    assert problems(tmp_path, CHANGE) == []
    # Without the change named, the id is in no specification.
    assert any("lists EF-n3w1, which neither" in problem for problem in problems(tmp_path))
    assert any("has no heading #requirement-ef-n3w1" in problem
               for problem in problems(tmp_path))


def test_a_capability_the_change_creates_resolves_against_its_delta(tmp_path: Path) -> None:
    # Before the archive writes it, the new capability has its index but no spec.md.
    capability = tmp_path / "openspec/specs/example-flow"
    capability.mkdir(parents=True)
    (capability / "index.md").write_text(INDEX, "utf-8")
    _delta(tmp_path, "## ADDED Requirements\n\n" + SPEC.split("## Requirements\n\n", 1)[1])

    assert problems(tmp_path, CHANGE) == []
    # Without the change named, nothing holds the ids, and spec.md is missing.
    assert any("its file spec.md does not exist" in problem for problem in problems(tmp_path))


@pytest.mark.parametrize("delta", [
    "",
    "## ADDED Requirements\n",
    "## REMOVED Requirements\n\n### Requirement: EF-zz00 Gone\n\n**Reason**: gone.\n",
    # A modification or rename needs a requirement already there, so neither can
    # write a missing spec.md, even naming every id the index lists.
    "## MODIFIED Requirements\n\n" + SPEC.split("## Requirements\n\n", 1)[1],
    "## RENAMED Requirements\n\n- FROM: `### Requirement: EF-zz00 Old`\n"
    "- TO: `### Requirement: EF-a8tf The flow starts`\n",
], ids=["empty", "empty-added", "removed-only", "modified-only", "renamed-only"])
def test_a_missing_spec_a_delta_adds_nothing_to_is_still_missing(tmp_path: Path,
                                                                 delta: str) -> None:
    capability = tmp_path / "openspec/specs/example-flow"
    capability.mkdir(parents=True)
    (capability / "index.md").write_text(INDEX, "utf-8")
    _delta(tmp_path, delta)

    assert any("its file spec.md does not exist" in problem
               for problem in problems(tmp_path, CHANGE))


def test_a_link_to_a_heading_a_new_capabilitys_delta_lacks_does_not_resolve(
        tmp_path: Path) -> None:
    capability = tmp_path / "openspec/specs/example-flow"
    capability.mkdir(parents=True)
    (capability / "index.md").write_text(INDEX + "\n[x](spec.md#not-a-heading)\n", "utf-8")
    _delta(tmp_path, "## ADDED Requirements\n\n" + SPEC.split("## Requirements\n\n", 1)[1])

    assert any("spec.md has no heading #not-a-heading" in problem
               for problem in problems(tmp_path, CHANGE))


def test_a_requirement_the_changes_delta_removes_is_held_to_nothing(tmp_path: Path) -> None:
    # Before the archive, the specification still holds a requirement the change
    # removes, here one written before the capability had ids.
    spec = SPEC + "\n### Requirement: An unindexed old rule\n\nIt MUST hold.\n"
    _capability(tmp_path, spec=spec)
    _delta(tmp_path, "## REMOVED Requirements\n\n### Requirement: An unindexed old rule\n\n"
                     "**Reason**: rewritten.\n\n**Migration**: EF-q4ze holds it.\n")

    assert problems(tmp_path, CHANGE) == []
    assert any("'An unindexed old rule' begins with no id" in problem
               for problem in problems(tmp_path))


RENAMED = ("## RENAMED Requirements\n\n"
           "- FROM: `### Requirement: EF-q4ze The flow ends`\n"
           "- TO: `### Requirement: EF-q4ze The flow stops`\n")


def test_a_rename_counts_its_new_name_and_drops_its_old(tmp_path: Path) -> None:
    deltas = read_deltas(RENAMED)

    assert (deltas.present, deltas.removed) == (["EF-q4ze The flow stops"],
                                                ["EF-q4ze The flow ends"])
    capability = _capability(tmp_path, index=INDEX.replace("the-flow-ends", "the-flow-stops"))
    assert capability_problems(capability, deltas) == []


def test_only_an_added_requirement_counts_as_added() -> None:
    deltas = read_deltas(ADDED + "\n" + RENAMED + "\n## MODIFIED Requirements\n\n"
                         "### Requirement: EF-a8tf The flow starts\n\nIt MUST start.\n"
                         "\n## REMOVED Requirements\n\n### Requirement: EF-zz00 Gone\n")

    assert deltas.added == ["EF-n3w1 The flow pauses"]
    assert read_deltas(RENAMED).added == []


def test_a_renamed_and_modified_requirement_is_one_requirement(tmp_path: Path) -> None:
    _capability(tmp_path, index=INDEX.replace("the-flow-ends", "the-flow-stops"))
    _delta(tmp_path, RENAMED + "\n## MODIFIED Requirements\n\n"
                     "### Requirement: EF-q4ze The flow stops\n\nIt MUST stop.\n")

    assert problems(tmp_path, CHANGE) == []


def test_a_link_to_a_heading_the_deltas_take_away_does_not_resolve(tmp_path: Path) -> None:
    # The index still points at the old name, which the archive will drop.
    _capability(tmp_path)
    _delta(tmp_path, RENAMED)

    assert any("has no heading #requirement-ef-q4ze-the-flow-ends" in problem
               for problem in problems(tmp_path, CHANGE))


def test_an_entry_linked_to_another_requirements_heading_is_named(tmp_path: Path) -> None:
    # Both links resolve, each to the other requirement.
    index = (INDEX.replace("spec.md#requirement-ef-a8tf-the-flow-starts", "SWAP")
             .replace("spec.md#requirement-ef-q4ze-the-flow-ends",
                      "spec.md#requirement-ef-a8tf-the-flow-starts")
             .replace("SWAP", "spec.md#requirement-ef-q4ze-the-flow-ends"))
    _capability(tmp_path, index=index)

    found = problems(tmp_path)

    assert found == [
        "example-flow: index.md:7: EF-a8tf links to spec.md#requirement-ef-q4ze-the-flow-"
        "ends, not to its requirement's heading spec.md#requirement-ef-a8tf-the-flow-starts",
        "example-flow: index.md:8: EF-q4ze links to spec.md#requirement-ef-a8tf-the-flow-"
        "starts, not to its requirement's heading spec.md#requirement-ef-q4ze-the-flow-ends",
    ]


def test_an_entry_linked_to_its_heading_in_another_file_is_named(tmp_path: Path) -> None:
    capability = _capability(tmp_path, index=INDEX.replace(
        "](spec.md#requirement-ef-q4ze", "](README.md#requirement-ef-q4ze"))
    (capability / "README.md").write_text("### Requirement: EF-q4ze The flow ends\n", "utf-8")

    assert problems(tmp_path) == [
        "example-flow: index.md:8: EF-q4ze links to README.md#requirement-ef-q4ze-the-flow-"
        "ends, not to its requirement's heading spec.md#requirement-ef-q4ze-the-flow-ends"]


def test_an_entry_linked_through_a_relative_path_to_its_heading_passes(tmp_path: Path) -> None:
    _capability(tmp_path, index=INDEX.replace("](spec.md#requirement-ef-q4ze",
                                              "](./spec.md#requirement-ef-q4ze"))

    assert problems(tmp_path) == []


def test_an_id_two_requirements_share_is_not_held_to_either_heading(tmp_path: Path) -> None:
    # The shared id is the problem; which heading its entry should reach is not
    # known until it is fixed.
    _capability(tmp_path, spec=SPEC.replace("EF-q4ze", "EF-a8tf"),
                index=INDEX.replace("[EF-q4ze](spec.md#requirement-ef-q4ze",
                                    "[EF-a8tf](spec.md#requirement-ef-a8tf"))

    found = problems(tmp_path)

    assert any("two requirements share the id EF-a8tf" in problem for problem in found)
    assert not any(" links to " in problem for problem in found), found


def test_an_entry_is_held_to_its_heading_as_the_deltas_leave_it(tmp_path: Path) -> None:
    # The old name's heading still resolves before the archive, but not once the
    # rename merges, and the entry's own heading is the new name.
    _capability(tmp_path)
    _delta(tmp_path, RENAMED)

    assert any("EF-q4ze links to spec.md#requirement-ef-q4ze-the-flow-ends, not to its "
               "requirement's heading spec.md#requirement-ef-q4ze-the-flow-stops" in problem
               for problem in problems(tmp_path, CHANGE))


def test_a_retired_id_written_as_its_old_link_is_retired(tmp_path: Path) -> None:
    index = INDEX.replace("- `EF-zz00` — its rule moved to EF-q4ze.",
                          "- [EF-zz00](spec.md) — its rule moved to EF-q4ze.")
    _capability(tmp_path, spec=SPEC.replace("EF-q4ze", "EF-zz00"),
                index=index.replace("EF-q4ze](spec.md#requirement-ef-q4ze",
                                    "EF-zz00](spec.md#requirement-ef-zz00"))

    assert any("the retired id EF-zz00 is in use" in problem for problem in problems(tmp_path))


def test_a_requirement_heading_inside_a_code_fence_is_no_requirement(tmp_path: Path) -> None:
    spec = SPEC.replace("It MUST end.", "It MUST end.\n\n```text\n### Requirement: Example\n```")
    _capability(tmp_path, spec=spec)

    assert problems(tmp_path) == []


def test_an_id_runs_only_to_its_four_characters(tmp_path: Path) -> None:
    _capability(tmp_path, spec=SPEC.replace("EF-a8tf The", "EF-a8tfThe"))

    assert any("'EF-a8tfThe flow starts' begins with no id" in problem
               for problem in problems(tmp_path))


def test_a_heading_inside_a_code_fence_is_no_anchor(tmp_path: Path) -> None:
    spec = SPEC.replace("It MUST end.", "It MUST end.\n\n```text\n# Not a heading\n```")
    _capability(tmp_path, spec=spec, index=INDEX + "\n[x](spec.md#not-a-heading)\n")

    assert any("has no heading #not-a-heading" in problem for problem in problems(tmp_path))


def test_a_heading_anchor_is_the_one_github_writes() -> None:
    assert slug("Requirement: CW-r3ka The engine is reached through one command") == (
        "requirement-cw-r3ka-the-engine-is-reached-through-one-command")
    assert slug("Requirement: CW-h8vm Make targets are a `convenience`") == (
        "requirement-cw-h8vm-make-targets-are-a-convenience")


def test_the_command_fails_naming_each_problem(tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    _capability(tmp_path, index=INDEX.replace("- [EF-q4ze]", "- see [EF-q4ze]"))

    assert main([""], root=tmp_path) == 1
    assert "FAIL: example-flow: index.md does not list EF-q4ze" in capsys.readouterr().out
    assert main([CHANGE, "other"], root=tmp_path) == 2


def test_the_command_passes_on_agreeing_indexes(tmp_path: Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    _capability(tmp_path)

    assert main([CHANGE], root=tmp_path) == 0
    assert capsys.readouterr().out.startswith("OK:")
