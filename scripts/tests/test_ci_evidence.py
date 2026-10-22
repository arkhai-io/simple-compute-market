"""Tests for dispatching a CI workflow and classing its run's failures against `dev`'s."""

from __future__ import annotations

import json
import subprocess
from typing import Sequence

import pytest

import ci_evidence

BRANCH = "feat/a-change"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
DEV_COMMIT = "1111111111111111111111111111111111111111"
NEWER_DEV_COMMIT = "2222222222222222222222222222222222222222"
OWED = "release · deployment contracts"
VMS = "py · vms-storefront"
BARE_METAL = "py · bare-metal-storefront"


class Fake:
    """`git` and `gh`, as the dispatch and the ancestry test see them."""

    def __init__(self, *, branch: str = BRANCH, newest: list[dict] | None = None,
                 known: Sequence[str] = (DEV_COMMIT, COMMIT),
                 ancestors: Sequence[str] = (DEV_COMMIT,), merge_base_status: int | None = None,
                 verify_status: int | None = None) -> None:
        self.branch = branch
        self.newest = [{"databaseId": 41}] if newest is None else newest
        self.known = set(known)
        self.ancestors = set(ancestors)
        self.merge_base_status = merge_base_status
        # `git rev-parse --verify`'s exit when it fails other than by not finding
        # the commit, as outside a repository.
        self.verify_status = verify_status
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str], *, capture_output: bool, text: bool,
                 check: bool) -> subprocess.CompletedProcess[str]:
        command = list(command)
        assert capture_output and text and not check
        self.commands.append(command)
        if command == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, self.branch + "\n", "")
        if command[:3] == ["gh", "run", "list"]:
            return subprocess.CompletedProcess(command, 0, json.dumps(self.newest), "")
        if command[:3] == ["gh", "workflow", "run"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:4] == ["git", "rev-parse", "--verify", "--quiet"]:
            if self.verify_status is not None:
                return subprocess.CompletedProcess(command, self.verify_status, "",
                                                   "fatal: not a git repository")
            known = command[4].removesuffix("^{commit}") in self.known
            return subprocess.CompletedProcess(command, 0 if known else 1, "", "")
        if command[:3] == ["git", "merge-base", "--is-ancestor"]:
            status = (self.merge_base_status if self.merge_base_status is not None
                      else 0 if command[3] in self.ancestors else 1)
            return subprocess.CompletedProcess(command, status, "", "fatal: broken")
        raise AssertionError(f"unexpected command: {command}")


# --- dispatch -------------------------------------------------------------------

def test_a_listed_workflow_is_dispatched_on_the_branch_after_its_newest_run_is_recorded(
) -> None:
    fake = Fake()
    said: list[str] = []

    assert ci_evidence.dispatch("tests.yml", runner=fake, echo=said.append) == 41

    assert fake.commands == [
        ["git", "branch", "--show-current"],
        ["gh", "run", "list", "--workflow", "tests.yml", "--branch", BRANCH, "--limit", "1",
         "--json", "databaseId"],
        ["gh", "workflow", "run", "tests.yml", "--ref", BRANCH],
    ]
    assert "CI_AFTER_RUN=41" in said


def test_a_branch_with_no_run_of_the_workflow_records_none() -> None:
    said: list[str] = []

    assert ci_evidence.dispatch("tests.yml", runner=Fake(newest=[]), echo=said.append) == 0
    assert "CI_AFTER_RUN=0" in said


@pytest.mark.parametrize("workflow", ["publish-pypi.yml", "e2e.yml", ""])
def test_a_workflow_not_on_the_list_is_refused_naming_the_list_and_nothing_runs(
        workflow: str) -> None:
    fake = Fake()

    with pytest.raises(ci_evidence.CIError, match="it may dispatch: tests.yml"):
        ci_evidence.dispatch(workflow, runner=fake, echo=lambda line: None)
    assert fake.commands == []


@pytest.mark.parametrize("workflow", ["publish-pypi.yml", "e2e.yml"])
def test_the_command_line_refuses_an_unlisted_workflow_with_exit_2(
        workflow: str, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake()

    assert ci_evidence.main(["dispatch", workflow], runner=fake) == 2
    assert f"{workflow} is not a workflow validation may dispatch" in capsys.readouterr().err
    assert fake.commands == []


def test_a_detached_head_is_refused_before_anything_is_dispatched() -> None:
    fake = Fake(branch="")

    with pytest.raises(ci_evidence.CIError, match="checked-out branch"):
        ci_evidence.dispatch("tests.yml", runner=fake, echo=lambda line: None)
    assert not any(command[:3] == ["gh", "workflow", "run"] for command in fake.commands)


def test_the_dispatchable_list_holds_no_publishing_workflow() -> None:
    assert ci_evidence.DISPATCHABLE == ("tests.yml",)


# --- the baseline -----------------------------------------------------------------

def _dev_runs(*runs: tuple[int, str, str]) -> list[dict]:
    return [{"databaseId": run_id, "headSha": sha, "conclusion": conclusion}
            for run_id, sha, conclusion in runs]


def test_the_baseline_is_the_newest_dev_run_the_branch_contains_skipping_a_newer_one() -> None:
    listed = _dev_runs((90, NEWER_DEV_COMMIT, "failure"), (80, DEV_COMMIT, "failure"),
                       (70, DEV_COMMIT, "success"))

    assert ci_evidence.baseline_run(listed, lambda sha: sha == DEV_COMMIT) == {
        "id": 80, "commit": DEV_COMMIT, "conclusion": "failure"}


def test_a_cancelled_dev_run_is_not_a_baseline() -> None:
    listed = _dev_runs((80, DEV_COMMIT, "cancelled"), (70, DEV_COMMIT, "failure"))

    assert ci_evidence.baseline_run(listed, lambda sha: True)["id"] == 70


def test_a_pull_requests_run_is_not_a_baseline() -> None:
    listed = [dict(run, event=event) for run, event in zip(
        _dev_runs((80, DEV_COMMIT, "failure"), (70, DEV_COMMIT, "failure")),
        ("pull_request", "push"))]

    assert ci_evidence.baseline_run(listed, lambda sha: True)["id"] == 70


def test_no_dev_run_of_code_the_branch_contains_is_no_baseline() -> None:
    listed = _dev_runs((90, NEWER_DEV_COMMIT, "failure"))

    assert ci_evidence.baseline_run(listed, lambda sha: False) is None
    assert ci_evidence.baseline_run([{"databaseId": "x"}, "a run"], lambda sha: True) is None


def test_ancestry_is_gits_and_a_commit_the_checkout_lacks_is_no_ancestor() -> None:
    fake = Fake()

    assert ci_evidence.is_ancestor(DEV_COMMIT, COMMIT, runner=fake)
    assert not ci_evidence.is_ancestor(COMMIT, COMMIT + "x", runner=Fake(ancestors=()))
    assert not ci_evidence.is_ancestor(NEWER_DEV_COMMIT, COMMIT, runner=fake)
    assert not any(command[:2] == ["git", "merge-base"] and command[3] == NEWER_DEV_COMMIT
                   for command in fake.commands)


@pytest.mark.parametrize("fake", [Fake(merge_base_status=128), Fake(verify_status=128)],
                         ids=["merge-base", "rev-parse"])
def test_a_failing_ancestry_check_is_an_error_not_an_answer(fake: Fake) -> None:
    with pytest.raises(ci_evidence.CIError, match="exited 128"):
        ci_evidence.is_ancestor(DEV_COMMIT, COMMIT, runner=fake)


# --- reading a run's failures -------------------------------------------------------

def _line(job: str, text: str, step: str = "Run tests", bom: bool = False) -> str:
    return f"{job}\t{step}\t{chr(0xFEFF) if bom else ''}2026-10-22T07:00:00.1234567Z {text}"


def _summary(job: str, *failures: str) -> list[str]:
    return [_line(job, "=========================== short test summary info "
                       "============================"),
            *(_line(job, failure) for failure in failures),
            _line(job, f"==== {len(failures)} failed, 10 passed in 1.00s ====")]


def _job(name: str, conclusion: str, failed_steps: Sequence[str] = ()) -> dict:
    return {"name": name, "conclusion": conclusion,
            "steps": [{"name": "Set up job", "conclusion": "success"},
                      *({"name": step, "conclusion": "failure"} for step in failed_steps)]}


def _jobs(*jobs: dict, lines: Sequence[str] = ()) -> dict[str, ci_evidence.Job]:
    return ci_evidence.read_jobs({"jobs": list(jobs)}, "\n".join(lines))


def test_each_short_summary_line_is_a_test_id_and_its_exception_type() -> None:
    jobs = _jobs(_job(VMS, "failure", ["Run tests"]), lines=_summary(
        VMS,
        "FAILED tests/unit/test_a.py::test_one - TimeoutError: timed out after 30s",
        "FAILED tests/unit/test_a.py::test_two[case - 1] - assert 1 == 0",
        "ERROR tests/unit/test_b.py::test_three - httpx.ConnectError: refused",
        "FAILED tests/unit/test_b.py::TestLong::test_with_an_id_too_long_for_its_message",
        "FAILED tests/unit/test_b.py::test_four - Failed: DID NOT RAISE",
        "SKIPPED [1] tests/unit/test_c.py:4: not here",
    ))

    assert jobs[VMS].failures == [
        ci_evidence.Failure("tests/unit/test_a.py::test_one", "TimeoutError", "FAILED"),
        ci_evidence.Failure("tests/unit/test_a.py::test_two[case - 1]", "AssertionError",
                            "FAILED"),
        ci_evidence.Failure("tests/unit/test_b.py::test_three", "httpx.ConnectError", "ERROR"),
        ci_evidence.Failure(
            "tests/unit/test_b.py::TestLong::test_with_an_id_too_long_for_its_message",
            None, "FAILED"),
        ci_evidence.Failure("tests/unit/test_b.py::test_four", "Failed", "FAILED"),
    ]


def test_an_entry_whose_message_runs_over_several_lines_hides_no_later_entry() -> None:
    # On CI pytest prints each entry's whole crash message.
    jobs = _jobs(_job(VMS, "failure", ["Run tests"]), lines=_summary(
        VMS,
        "FAILED tests/test_vm.py::test_first - assert 1 == 2",
        " +  where 1 = len([1])",
        "",
        "FAILED tests/test_vm.py::test_second - RuntimeError: gave up",
        "3 attempts in 5.0s",
        "===== captured from the server =====",
        "5 failed in 2.0s, then the server said no",
        "FAILED tests/test_vm.py::test_third - ValueError: bad",
        "first detail line",
    ))

    assert [(f.test, f.type) for f in jobs[VMS].failures] == [
        ("tests/test_vm.py::test_first", "AssertionError"),
        ("tests/test_vm.py::test_second", "RuntimeError"),
        ("tests/test_vm.py::test_third", "ValueError")]


@pytest.mark.parametrize("closing", [
    "1 failed, 132 passed, 1 skipped, 118 deselected in 113.84s (0:01:53)",
    "==== 2 failed, 10 passed, 3 warnings in 1.00s ====",
])
def test_pytests_closing_count_ends_the_summary(closing: str) -> None:
    jobs = _jobs(_job(VMS, "failure", ["Run tests"]), lines=[
        _line(VMS, "=== short test summary info ==="),
        _line(VMS, "FAILED tests/test_vm.py::test_one - ValueError: one"),
        _line(VMS, closing),
        _line(VMS, "FAILED tests/test_vm.py::not_in_the_summary - ValueError: later"),
    ])

    assert [f.test for f in jobs[VMS].failures] == ["tests/test_vm.py::test_one"]


def test_a_summary_with_no_closing_count_ends_with_its_step() -> None:
    jobs = _jobs(_job(VMS, "failure", ["Run tests"]), lines=[
        _line(VMS, "=== short test summary info ==="),
        _line(VMS, "FAILED tests/test_vm.py::test_cut - ValueError: cut short"),
        _line(VMS, "FAILED tests/x.py::not_a_failure - printed by a later step",
              step="Collect logs"),
        _line(VMS, "=== short test summary info ===", step="Run more"),
        _line(VMS, "FAILED tests/y.py::test_runner - ValueError: one", step="Run more"),
        _line(VMS, "##[error]Process completed with exit code 1.", step="Run more"),
        _line(VMS, "FAILED tests/y.py::after_the_runner - ValueError: not one",
              step="Run more"),
    ])

    assert [f.test for f in jobs[VMS].failures] == ["tests/test_vm.py::test_cut",
                                                    "tests/y.py::test_runner"]


def test_a_plain_assert_is_an_assertion_error() -> None:
    assert ci_evidence.exception_type("assert 1 == 0") == "AssertionError"
    assert ci_evidence.exception_type("AssertionError: wrong") == "AssertionError"
    assert ci_evidence.exception_type("the service said: no") is None
    assert ci_evidence.exception_type(None) is None


def test_only_the_short_summary_is_read_with_its_timestamp_mark_and_colour_gone() -> None:
    jobs = _jobs(_job(VMS, "failure"), _job(BARE_METAL, "success"), lines=[
        _line(VMS, "FAILED tests/x.py::not_a_summary_line - ValueError: printed earlier"),
        _line(VMS, "=== short test summary info ===", bom=True),
        _line(VMS, "\x1b[31mFAILED\x1b[0m tests/x.py::test_red - ValueError: red"),
        _line(VMS, "2 failed in 0.1s"),
        _line(VMS, "FAILED tests/x.py::after_the_summary - ValueError: later"),
        _line(BARE_METAL, "FAILED tests/y.py::another_job - ValueError: not a summary"),
    ])

    assert jobs[VMS].failures == [ci_evidence.Failure("tests/x.py::test_red", "ValueError",
                                                      "FAILED")]
    assert jobs[BARE_METAL].failures == []
    assert len(jobs[VMS].lines) == 5


def test_a_job_printing_no_short_summary_keeps_its_failing_step_and_error_lines() -> None:
    jobs = _jobs(_job(OWED, "failure", ["Install Helm"]), lines=[
        _line(OWED, "##[error]Unable to download helm", step="Install Helm"),
        _line(OWED, "##[error]Process completed with exit code 1.", step="Install Helm"),
    ])

    assert jobs[OWED].failed_steps == ["Install Helm"]
    assert jobs[OWED].errors == ["Unable to download helm", "Process completed with exit code 1."]
    assert jobs[OWED].failures == []


# --- the delta's scenarios, as classes over fixture logs -----------------------------

def _compare(run: Sequence[tuple[dict, list[str]]],
             baseline: Sequence[tuple[dict, list[str]]] | None) -> dict[str, dict]:
    run_jobs = _jobs(*(job for job, _ in run), lines=[line for _, lines in run for line in lines])
    baseline_jobs = None if baseline is None else _jobs(
        *(job for job, _ in baseline), lines=[line for _, lines in baseline for line in lines])
    return {job["name"]: job for job in ci_evidence.compare(run_jobs, baseline_jobs)}


def _classes(job: dict) -> list[tuple[str | None, str]]:
    return [(failure.get("test"), failure["class"]) for failure in job["failures"]]


TIMEOUT = "FAILED tests/test_vm.py::test_slow - TimeoutError: timed out"
ABORT = "FAILED tests/test_bm.py::test_abort_all_is_not_previewed - AssertionError: previewed"


def test_owed_ci_evidence_beside_jobs_that_fail_on_dev() -> None:
    failing_on_dev = [(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT)),
                      (_job(BARE_METAL, "failure", ["Run tests"]), _summary(BARE_METAL, ABORT))]

    compared = _compare([(_job(OWED, "success"), []), *failing_on_dev],
                        [(_job(OWED, "success"), []), *failing_on_dev])

    assert compared[OWED]["failures"] == []
    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "inherited")]
    assert _classes(compared[BARE_METAL]) == [
        ("tests/test_bm.py::test_abort_all_is_not_previewed", "inherited")]
    assert ci_evidence.classes(list(compared.values())) == {
        "inherited": 2, "new": 0, "uncomparable": 0}


def test_a_job_not_owed_fails_only_on_the_branch() -> None:
    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))],
                        [(_job(VMS, "success"), [])])

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "new")]


def test_a_new_failure_in_a_job_that_already_fails_on_dev() -> None:
    other = "FAILED tests/test_vm.py::test_other - KeyError: 'listing'"

    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT, other))],
                        [(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))])

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "inherited"),
                                       ("tests/test_vm.py::test_other", "new")]


def test_a_test_that_fails_on_dev_fails_another_way_on_the_branch() -> None:
    another_way = "FAILED tests/test_vm.py::test_slow - AssertionError: wrong status"

    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, another_way))],
                        [(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))])

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "new")]


def test_no_dev_run_of_the_branchs_code() -> None:
    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))], None)

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "uncomparable")]
    assert "no completed dev run" in compared[VMS]["reason"]


def _helm_failure(error: str = "Unable to download helm") -> tuple[dict, list[str]]:
    return (_job(OWED, "failure", ["Install Helm"]),
            [_line(OWED, f"##[error]{error}", step="Install Helm")])


def test_a_job_printing_no_failing_test_is_compared_by_its_failing_step() -> None:
    compared = _compare([_helm_failure()], [_helm_failure()])

    assert compared[OWED]["failures"] == [{"step": "Install Helm",
                                           "errors": ["Unable to download helm"],
                                           "class": "inherited"}]


def test_a_step_failing_only_on_the_branch_is_new() -> None:
    compared = _compare([_helm_failure()], [(_job(OWED, "success"), [])])

    assert [failure["class"] for failure in compared[OWED]["failures"]] == ["new"]


def test_a_step_failing_on_dev_with_other_error_lines_is_new() -> None:
    compared = _compare([_helm_failure("Unable to download helm")],
                        [_helm_failure("Checksum mismatch")])

    assert [failure["class"] for failure in compared[OWED]["failures"]] == ["new"]


def test_a_step_failing_where_dev_fails_another_step_is_new() -> None:
    compared = _compare([(_job(VMS, "failure", ["Install uv"]),
                          [_line(VMS, "##[error]no uv", step="Install uv")])],
                        [(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))])

    assert [failure["class"] for failure in compared[VMS]["failures"]] == ["new"]


def test_a_step_failing_where_dev_fails_only_another_step_is_new() -> None:
    compared = _compare([_helm_failure()],
                        [(_job(OWED, "failure", ["Run contracts"]),
                          [_line(OWED, "##[error]exit 1", step="Run contracts")])])

    assert [failure["class"] for failure in compared[OWED]["failures"]] == ["new"]


def test_failing_tests_where_dev_fails_only_a_later_step_are_new() -> None:
    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))],
                        [(_job(VMS, "failure", ["Upload logs"]),
                          [_line(VMS, "##[error]no artifact", step="Upload logs")])])

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "new")]


def test_a_step_failing_where_dev_names_failing_tests_at_it_cannot_be_compared() -> None:
    compared = _compare([(_job(VMS, "failure", ["Run tests"]),
                          [_line(VMS, "##[error]Process completed with exit code 2.")])],
                        [(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))])

    assert [failure["class"] for failure in compared[VMS]["failures"]] == ["uncomparable"]
    assert "only the step that failed" in compared[VMS]["reason"]


def test_a_job_failing_at_no_step_cannot_be_compared() -> None:
    timed_out = (_job(VMS, "timed_out"), [_line(VMS, "##[error]The job exceeded its time")])

    compared = _compare([timed_out], [timed_out])

    assert compared[VMS]["failures"] == [{"step": None, "errors": ["The job exceeded its time"],
                                          "class": "uncomparable"}]
    assert "naming no failing step" in compared[VMS]["reason"]


def test_a_job_whose_lines_the_log_does_not_hold_cannot_be_compared() -> None:
    # As when the log's job column does not name the job as `--json jobs` does.
    nothing = (_job(VMS, "failure", ["Run tests"]), [])

    compared = _compare([nothing], [nothing])

    assert [failure["class"] for failure in compared[VMS]["failures"]] == ["uncomparable"]
    assert "holds no line of this job" in compared[VMS]["reason"]
    baseline_empty = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))],
                              [nothing])
    assert "baseline's log holds no line" in baseline_empty[VMS]["reason"]


def test_a_step_whose_error_lines_say_only_that_it_failed_cannot_be_compared() -> None:
    # A TypeScript or Rust job's new failing test shows as nothing more than this.
    exit_only = (_job(VMS, "failure", ["Run tests"]),
                 [_line(VMS, "##[error]Process completed with exit code 1.")])

    compared = _compare([exit_only], [exit_only])

    assert [failure["class"] for failure in compared[VMS]["failures"]] == ["uncomparable"]
    assert "say only that it failed" in compared[VMS]["reason"]


def test_a_job_the_baseline_skipped_cannot_be_compared() -> None:
    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))],
                        [(_job(VMS, "skipped"), [])])

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "uncomparable")]
    assert "skipped" in compared[VMS]["reason"]


def test_failing_tests_beside_a_baseline_failing_only_at_that_step_cannot_be_compared(
) -> None:
    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))],
                        [(_job(VMS, "timed_out", ["Run tests"]),
                          [_line(VMS, "##[error]The operation was canceled.")])])

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "uncomparable")]
    assert "only the step that failed" in compared[VMS]["reason"]


def test_why_there_is_no_baseline_is_the_callers_to_say() -> None:
    run_jobs = _jobs(_job(VMS, "failure", ["Run tests"]), lines=_summary(VMS, TIMEOUT))

    compared = ci_evidence.compare(run_jobs, None, "the baseline could not be read")

    assert compared[0]["reason"] == "the baseline could not be read"
    assert compared[0]["failures"][0]["class"] == "uncomparable"


def test_a_job_the_baseline_does_not_have_cannot_be_compared() -> None:
    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))],
                        [(_job(BARE_METAL, "success"), [])])

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "uncomparable")]
    assert "no job of this name" in compared[VMS]["reason"]


def test_a_failure_whose_line_names_no_type_cannot_be_compared_by_its_id_alone() -> None:
    long_id = "FAILED tests/test_vm.py::TestStage::test_with_an_id_too_long_for_its_message"

    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, long_id, TIMEOUT))],
                        [(_job(VMS, "failure", ["Run tests"]), _summary(VMS, long_id, TIMEOUT))])

    assert _classes(compared[VMS]) == [
        ("tests/test_vm.py::TestStage::test_with_an_id_too_long_for_its_message", "uncomparable"),
        ("tests/test_vm.py::test_slow", "inherited")]
    assert compared[VMS]["failures"][0]["reason"] == "its line names no exception type"


def test_an_exception_raised_with_no_message_is_its_type() -> None:
    bare = "FAILED tests/test_vm.py::test_slow - TimeoutError"
    other_way = "FAILED tests/test_vm.py::test_slow - KeyError"

    assert ci_evidence.exception_type("TimeoutError") == "TimeoutError"
    assert ci_evidence.exception_type("asyncio.CancelledError") == "asyncio.CancelledError"
    assert ci_evidence.exception_type("boom") is None
    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, other_way))],
                        [(_job(VMS, "failure", ["Run tests"]), _summary(VMS, bare))])
    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "new")]


def test_a_test_erroring_where_dev_fails_it_is_new() -> None:
    erroring = "ERROR tests/test_vm.py::test_slow - TimeoutError: timed out"

    compared = _compare([(_job(VMS, "failure", ["Run tests"]), _summary(VMS, erroring))],
                        [(_job(VMS, "failure", ["Run tests"]), _summary(VMS, TIMEOUT))])

    assert _classes(compared[VMS]) == [("tests/test_vm.py::test_slow", "new")]


def test_a_passing_or_skipped_job_has_no_failures() -> None:
    compared = _compare([(_job(OWED, "success"), []), (_job(VMS, "skipped"), [])], None)

    assert compared[OWED]["failures"] == compared[VMS]["failures"] == []
