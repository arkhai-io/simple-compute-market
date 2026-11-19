"""Every numbered task of a change's task list sits under its own section's heading,
and every owed line names an owed evidence kind and a safe argument."""

from __future__ import annotations

from pathlib import Path

import pytest

from change_workflow import next_step as nxt
from change_workflow import tasks as check
from change_workflow_fixtures import configured, evidence_kind

CHANGE = "shape-bounds"
# Joined at run time: this file is scanned for task-number references like any
# other, and a problem written out whole would be a finding against the test.
STRAYED = "task " + "2.1 sits under `## 1. First`"
MISPLACED = "task " + "1.3 sits under `## 2A. Second again`"
WELL_FORMED = """## 1. First

- [x] 1.1 Done.
- [ ] 1.2 Open.

## 2. Second

- [ ] 2.1 Open.

## 2A. Second again

- [ ] 2A.1 Open.
  - [ ] 2A.2 Nested.

## 3. Closeout

- [ ] 3.1 Archive.
"""


def test_a_well_formed_list_has_no_problem() -> None:
    assert nxt.task_problems(WELL_FORMED) == []


def test_a_task_under_another_sections_heading_is_named_with_the_heading() -> None:
    problems = nxt.task_problems(WELL_FORMED.replace("## 2. Second\n\n", ""))

    assert problems == [f"line 6: {STRAYED}"]


def test_a_misplaced_task_is_named_wherever_it_sits() -> None:
    text = WELL_FORMED.replace("- [ ] 2A.1 Open.", "- [ ] 2A.1 Open.\n- [ ] 1.3 Strayed.")

    assert nxt.task_problems(text) == [f"line 13: {MISPLACED}"]


def test_unnumbered_tasks_and_tasks_before_any_heading_are_not_checked() -> None:
    text = "- [ ] 9.1 Before any heading.\n\n## 1. First\n\n- [ ] Do it.\n- [x] Done it.\n"

    assert nxt.task_problems(text) == []


def test_a_list_without_numbered_headings_is_not_checked() -> None:
    assert nxt.task_problems("## Tasks\n\n- [ ] 1.1 One.\n- [ ] 2.1 Two.\n") == []


def test_tasks_under_an_unnumbered_heading_after_a_section_are_not_checked() -> None:
    text = WELL_FORMED + "\n## Deferred, carried out of this change\n\n- [ ] 7.1 Later.\n"

    assert nxt.task_problems(text) == []


def test_a_section_id_is_matched_whatever_its_case() -> None:
    assert nxt.task_problems("## 5A. Fifth\n\n- [ ] 5a.1 Lower.\n- [ ] 5A.2 Upper.\n") == []


def test_a_list_ending_with_its_closeout_section_has_no_closeout_problem() -> None:
    assert nxt.closeout_problems(WELL_FORMED) == []


def test_a_list_with_no_section_titled_closeout_is_named_at_its_last_section() -> None:
    text = WELL_FORMED.replace("## 3. Closeout", "## 3. Plan closeout")

    assert nxt.closeout_problems(text) == [
        "line 15: no section is titled `Closeout`; the task list ends with its closeout "
        "section, `## N. Closeout`"]


def test_a_section_after_the_closeout_section_is_named() -> None:
    text = WELL_FORMED + "\n## 3b. Closeout's fixes\n\n- [ ] 3b.1 Fix.\n"

    assert nxt.closeout_problems(text) == [
        "line 19: section 3b follows the closeout section; the closeout section is the "
        "task list's last"]


def test_a_second_closeout_section_is_named() -> None:
    text = WELL_FORMED.replace("## 2. Second", "## 2. Closeout")

    assert nxt.closeout_problems(text) == [
        "line 15: a second section is titled `Closeout`",
        "line 10: section 2A follows the closeout section; the closeout section is the "
        "task list's last"]


def test_a_list_without_numbered_headings_has_no_closeout_problem() -> None:
    assert nxt.closeout_problems("## Tasks\n\n- [ ] 1.1 One.\n") == []


def _repository(tmp_path: Path, text: str | None) -> Path:
    directory = tmp_path / "openspec/changes" / CHANGE
    directory.mkdir(parents=True)
    if text is not None:
        (directory / nxt.TASKS_FILE).write_text(text, "utf-8")
    return tmp_path


def test_the_command_names_each_problem_and_fails(tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path, WELL_FORMED.replace("## 2. Second\n\n", ""))

    assert check.main([CHANGE], root=root) == 1

    # A failed check gives its reason on standard error.
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(f"openspec/changes/{CHANGE}/{nxt.TASKS_FILE}:line 6: {STRAYED}")
    assert "FAIL:" in err


def test_the_command_passes_a_well_formed_list(tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main([CHANGE], root=_repository(tmp_path, WELL_FORMED)) == 0
    assert capsys.readouterr().out.startswith("OK:")


def test_the_command_passes_a_change_with_no_task_list_yet(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main([CHANGE], root=_repository(tmp_path, None)) == 0
    assert "no task list yet" in capsys.readouterr().out


def test_the_command_reports_a_refused_owed_line(tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    """CW-r5qk's scenario "An owed argument climbs out of its directory": `check
    tasks` refuses the line, naming its section."""
    root = _repository(tmp_path, WELL_FORMED.replace(
        "- [x] 1.1 Done.\n", "- [x] 1.1 Done.\n  Owed by validation (ci ..): job lint — passes\n"))
    configured(root, evidence_kind("ci", required="owed", identity="commit", start="a",
                                   collect="b"))

    assert check.main([CHANGE], root=root) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert (f"openspec/changes/{CHANGE}/{nxt.TASKS_FILE}:4: section 1's owed line names "
            "'..', which is no argument but a directory") in err
    assert "FAIL: an owed line" in err


# Owed lines: each names its kind and one safe argument.

def _owed(line: str, kinds: tuple[str, ...] = ("ci",)) -> check.Owed:
    (owed,) = check.read_owed(f"## 1. First\n\n- [x] 1.1 Done.\n  {line}\n", kinds)
    return owed


@pytest.mark.parametrize("line,kinds,kind,argument", [
    ("Owed by validation (ci tests.yml): job `py` — passes", ("ci",), "ci", "tests.yml"),
    ("- Owed by validation (pipeline e2e.yml): scenario test_spot_deal_settles passes",
     ("pipeline", "ci"), "pipeline", "e2e.yml"),
    # A line naming no kind owes the repository's one owed kind, its argument the
    # first word in backticks.
    ("Owed by validation: `tests.yml`, job `py`, its suite passing.", ("ci",), "ci",
     "tests.yml"),
    ("Owed by validation: the `docker.yml` run, job `build`", ("ci",), "ci", "docker.yml"),
])
def test_an_owed_line_names_its_kind_and_argument(line: str, kinds: tuple[str, ...],
                                                  kind: str, argument: str) -> None:
    """CW-r5qk: the named form, and a line naming no kind read as the one owed kind,
    `tests.yml` in backticks owing `ci tests.yml`."""
    owed = _owed(line, kinds)

    assert (owed.section, owed.line, owed.kind, owed.argument, owed.refusal) == (
        "1", 4, kind, argument, None)


@pytest.mark.parametrize("line,kinds,refused", [
    ("Owed by validation (ci ..): job lint — passes", ("ci",),
     "section 1's owed line names '..', which is no argument but a directory"),
    ("Owed by validation (ci .): job lint", ("ci",), "names '.', which is no argument"),
    ("Owed by validation (ci a/b.yml): job lint", ("ci",), "names 'a/b.yml', which holds a `/`"),
    ("Owed by validation (ci tests.yml docker.yml): x", ("ci",), "which holds a `/`, whitespace"),
    ("Owed by validation (ci *.yml): x", ("ci",), "names '*.yml', which holds"),
    ("Owed by validation (ci t?.yml): x", ("ci",), "names 't?.yml', which holds"),
    ("Owed by validation (ci [ab].yml): x", ("ci",), "names '[ab].yml', which holds"),
    ("Owed by validation (ci a].yml): x", ("ci",), "names 'a].yml', which holds"),
    ("Owed by validation (ci): job lint", ("ci",), "section 1's owed line names no argument"),
    ("Owed by validation (): job lint", ("ci",), "names no kind in its parentheses"),
    ("Owed by validation (local x): job lint", ("ci",),
     "names 'local', which is no evidence kind the configuration declares owed; owed: ci"),
    ("Owed by validation: `tests.yml`, job `py`", ("pipeline", "ci"),
     "names no kind, and the configuration declares several kinds owed: pipeline, ci"),
    ("Owed by validation: `tests.yml`, job `py`", (),
     "names no kind, and the configuration declares no kind owed"),
    ("Owed by validation: job lint of tests.yml — passes", ("ci",),
     "names no argument in backticks"),
    ("Owed by validation: `job lint` — passes", ("ci",), "names 'job lint', which holds"),
    ("Owed by validation ci tests.yml", ("ci",), "is neither `Owed by validation (<kind> "),
])
def test_an_owed_line_is_refused_naming_its_section(line: str, kinds: tuple[str, ...],
                                                    refused: str) -> None:
    """CW-r5qk: a line naming no argument or an unsafe one, a kind that is not owed,
    or no kind where none or several are owed, is refused, naming its section."""
    owed = _owed(line, kinds)

    assert owed.refusal is not None and refused in owed.refusal
    assert owed.argument is None


def test_a_refused_line_keeps_the_owed_kind_it_names() -> None:
    """A refused line is reported under its kind only when the kind is owed."""
    assert _owed("Owed by validation (ci ..): job lint").kind == "ci"
    assert _owed("Owed by validation: job lint").kind == "ci"
    assert _owed("Owed by validation: `t.yml`", ("pipeline", "ci")).kind is None
    assert _owed("Owed by validation (local x): job lint").kind is None


def test_only_the_sections_given_as_complete_owe_anything() -> None:
    text = ("## 1. A\n\n- [x] 1.1 x.\n  Owed by validation (ci a.yml): job a\n\n"
            "## 2. B\n\n- [ ] 2.1 y.\n  Owed by validation (ci ..): job b\n\n"
            "## 3. Closeout\n\n- [ ] 3.1 z.\n")

    assert [(o.section, o.argument) for o in check.read_owed(text, ("ci",), ["1"])] == [
        ("1", "a.yml")]
    assert [o.section for o in check.read_owed(text, ("ci",))] == ["1", "2"]


def test_the_owed_lines_of_a_task_list_are_its_complete_sections(tmp_path: Path) -> None:
    tasks = tmp_path / nxt.TASKS_FILE
    tasks.write_text("## 1. A\n\n- [x] 1.1 x.\n  Owed by validation (ci a.yml): job a\n\n"
                     "## 2. B\n\n- [ ] 2.1 y.\n  Owed by validation (ci b.yml): job b\n", "utf-8")

    assert [(o.section, o.kind, o.argument) for o in check.owed_lines(tasks, ("ci",))] == [
        ("1", "ci", "a.yml")]
    assert check.owed_lines(tmp_path / "missing.md", ("ci",)) == []


def test_the_command_refuses_an_unknown_change_and_a_missing_argument(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path, WELL_FORMED)

    # An unknown change is a refusal; only a malformed argument is a usage error.
    assert check.main(["missing"], root=root) == 1
    assert "missing" in capsys.readouterr().err
    assert check.main([], root=root) == 2
    assert "usage" in capsys.readouterr().err
