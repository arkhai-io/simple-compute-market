"""Tests for the check that runs two changes' Helm validations at once."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import pytest

import change_clone
import validate_parallel as check

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE = "arkhai-node-operator"
POD = f"{RELEASE}-e2e-tests-e2e-scenarios"
FIRST, SECOND = "pilot", "other-change"
ATTEMPT = Path(".snapshot/validation/0123456789ab/helm/1")
STARTED = datetime(2026, 10, 21, 19, 0, 0, 500000, tzinfo=timezone.utc)


def _stamp(minutes: float) -> str:
    return (STARTED.replace(microsecond=0) + timedelta(minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _pod(name: str, namespace: str, images: Sequence[str], *, minutes: float = 10,
         claims: Sequence[str] = (), exit_code: int | None = None,
         ran: tuple[float, float] | None = None, release: str = RELEASE) -> dict:
    pod = {"metadata": {"name": name, "namespace": namespace,
                        "creationTimestamp": _stamp(minutes),
                        "labels": {"app.kubernetes.io/instance": release}},
           "spec": {"containers": [{"image": image} for image in images],
                    "volumes": [{"name": claim, "persistentVolumeClaim": {"claimName": claim}}
                                for claim in claims]},
           "status": {}}
    if exit_code is not None:
        started, finished = ran or (20, 25)
        pod["status"]["containerStatuses"] = [{"state": {"terminated": {
            "exitCode": exit_code, "startedAt": _stamp(started),
            "finishedAt": _stamp(finished)}}}]
    return pod


class Namespace:
    """One change's run as the check reads it afterwards: what its summary kept,
    and what its namespace holds once both runs have ended."""

    def __init__(self, change: str, ran: tuple[float, float]) -> None:
        self.change = change
        self.name = f"validate-{change}"
        self.status = 0
        self.passed = True
        self.summary_namespace = self.name
        # A summary.json, and a pods.json's text, to write in place of the ones the
        # fields here make.
        self.summary: object = None
        self.kept_text: str | None = None
        self.overlay = {"storefront": {"image": {"tag": f"storefront-{change}"}},
                        "e2e-tests": {"image": {"tag": f"e2e-tests-{change}"}}}
        storefront = f"arkhai:storefront-{change}"
        self.kept = [_pod(f"{RELEASE}-storefront-bob-1", self.name, [storefront],
                          claims=[f"{RELEASE}-storefront-data"]),
                     _pod(POD, self.name, [f"arkhai:e2e-tests-{change}"],
                          claims=["arkhai-buyer-profiles"])]
        self.scenario = _pod(POD, self.name, [f"arkhai:e2e-tests-{change}"],
                             minutes=19, claims=["arkhai-buyer-profiles"], exit_code=0, ran=ran)
        self.pods = [self.scenario]
        # The release's own volume, and the deal test's, which no chart labels.
        self.volumes = [{"metadata": {"name": f"{RELEASE}-storefront-data",
                                      "creationTimestamp": _stamp(5),
                                      "labels": {"app.kubernetes.io/instance": RELEASE}}},
                        {"metadata": {"name": "arkhai-buyer-profiles",
                                      "creationTimestamp": _stamp(5)}}]
        self.workloads = [{"kind": "Deployment",
                           "metadata": {"name": f"{RELEASE}-storefront-bob",
                                        "labels": {"app.kubernetes.io/instance": RELEASE}},
                           "spec": {"replicas": 0}}]
        self.history = [{"revision": 3, "updated": "2026-10-20T10:00:00.123456789+00:00",
                         "description": "Upgrade complete"},
                        {"revision": 4, "updated": _stamp(6).replace("Z", ".123456789Z"),
                         "description": "Upgrade complete"}]


class Fake:
    """Two clones' runs and the cluster they leave, for the check's commands."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "workspace"
        self.root.mkdir()
        self.clones = {change: tmp_path / "workspace.changes" / change
                       for change in (FIRST, SECOND)}
        self.namespaces = {FIRST: Namespace(FIRST, (20, 25)),
                           SECOND: Namespace(SECOND, (22, 27))}
        self.events: list[str] = []
        self.launched: list[tuple[list[str], Path, Path]] = []
        self.reads: list[list[str]] = []
        self.unreadable: set[str] = set()
        # Runs whose launch raises, as Popen does when it cannot start the command.
        self.cannot_start: set[str] = set()
        # A run whose wait returns only once the other run's end has been taken.
        self.ends_last: str | None = None
        self.other_ended = threading.Event()
        self.lock = threading.Lock()
        # The check's start, each run's start, then each run's end.
        self.times = [STARTED, STARTED + timedelta(seconds=1),
                      STARTED + timedelta(seconds=2), STARTED + timedelta(minutes=30),
                      STARTED + timedelta(minutes=31)]
        self.ticks = 0

    def clock(self) -> datetime:
        with self.lock:
            now = self.times[self.ticks]
            self.ticks += 1
            if self.ticks == 4:
                # The first end taken: the run waiting on the other may now end.
                self.other_ended.set()
            return now

    def locate(self, clone: Path) -> str:
        return clone.name

    def launch(self, command: Sequence[str], cwd: Path, log: Path) -> "Fake.Process":
        change = command[command.index("validate-helm") + 1].removeprefix("CHANGE=")
        self.launched.append((list(command), cwd, log))
        self.events.append(f"launch {change}")
        if change in self.cannot_start:
            raise FileNotFoundError(2, "No such file or directory", "make")
        self._leave(change, cwd, log)
        return Fake.Process(self, change)

    class Process:
        def __init__(self, fake: "Fake", change: str) -> None:
            self.fake, self.change = fake, change

        def wait(self) -> int:
            if self.change == self.fake.ends_last:
                assert self.fake.other_ended.wait(timeout=10), "the other run's end was not taken"
            with self.fake.lock:
                self.fake.events.append(f"wait {self.change}")
            return self.fake.namespaces[self.change].status

    def _leave(self, change: str, clone: Path, log: Path) -> None:
        state = self.namespaces[change]
        log.parent.mkdir(parents=True, exist_ok=True)
        if state.status != 0 and not state.passed and state.summary_namespace is None:
            log.write_text("ERROR: the Docker daemon is not reachable\n", "utf-8")
            return
        attempt = clone / ATTEMPT
        attempt.mkdir(parents=True)
        (attempt / "images.json").write_text(json.dumps(state.overlay), "utf-8")
        (attempt / "pods.json").write_text(state.kept_text or json.dumps({"items": state.kept}),
                                           "utf-8")
        steps = [{"name": "deploy", "result": "passed"}]
        if not state.passed:
            steps.append({"name": "e2e", "result": "failed"})
        (attempt / "summary.json").write_text(json.dumps(state.summary if state.summary
                                                         is not None else {
            "part": "helm", "attempt": 1, "passed": state.passed, "steps": steps,
            "namespace": state.summary_namespace,
            "evidence": {"pod_statuses": str(ATTEMPT / "pods.json"),
                         "scenarios": {"pod": POD, "exit_code": 0}}}), "utf-8")
        log.write_text(f"helm validation of 0123456789ab, attempt 1\n"
                       f"Attempt 1 logs and summary.json: {ATTEMPT}\n", "utf-8")

    def read(self, command: Sequence[str]) -> str:
        command = list(command)
        self.reads.append(command)
        joined = " ".join(command)
        if any(text in joined for text in self.unreadable):
            raise check.CheckError(f"{joined} failed: refused")
        if command[:2] == ["make", "-s"]:
            return RELEASE + "\n"
        if command[0] == "kubectl":
            assert command[1:3] == ["--context", "docker-desktop"], command
            command = ["kubectl", *command[3:]]
        elif command[0] == "helm":
            assert command[command.index("--kube-context") + 1] == "docker-desktop", command
        state = next(state for state in self.namespaces.values()
                     if state.name == command[command.index("--namespace") + 1])
        if command[:3] == ["kubectl", "get", "pod"]:
            return json.dumps(state.scenario)
        if command[:2] == ["helm", "history"]:
            return json.dumps(state.history)
        if command[:3] == ["kubectl", "get", "pvc"]:
            return json.dumps({"items": state.volumes})
        if command[:3] == ["kubectl", "get", "pods"]:
            return json.dumps({"items": _selected(command, state.pods)})
        if command[:3] == ["kubectl", "get", "deployments,statefulsets"]:
            return json.dumps({"items": _selected(command, state.workloads)})
        raise AssertionError(f"unexpected read: {command}")

    def report(self) -> "check.Report":
        validation = check.ParallelValidation(
            [self.clones[FIRST], self.clones[SECOND]], root=self.root, launch=self.launch,
            read=self.read, locate=self.locate, clock=self.clock)
        self.validation = validation
        return validation.run()


def _selected(command: list[str], items: list[dict]) -> list[dict]:
    """The items a read's `--selector key=value` selects, as the cluster answers it."""
    if "--selector" not in command:
        return items
    key, _, value = command[command.index("--selector") + 1].partition("=")
    return [item for item in items
            if (item["metadata"].get("labels") or {}).get(key) == value]


def _checks(report: "check.Report") -> dict[str, "check.Check"]:
    return {result.name: result for result in report.checks}


def test_two_isolated_runs_pass_every_check(tmp_path: Path) -> None:
    fake = Fake(tmp_path)

    report = fake.report()

    found = _checks(report)
    assert report.passed, check.render(report)
    assert list(found) == ["together", "results", "namespaces", "tags", "scenario pods",
                           "untouched"]
    assert found["together"].detail == (
        "pilot 19:00:01–19:30:00; other-change 19:00:02–19:31:00; "
        "their scenario pods ran together") or found["together"].detail == (
        "pilot 19:00:01–19:31:00; other-change 19:00:02–19:30:00; "
        "their scenario pods ran together")
    assert found["results"].detail.splitlines() == [
        f"pilot passed, attempt 1 in {ATTEMPT}", f"other-change passed, attempt 1 in {ATTEMPT}"]
    assert found["namespaces"].detail == "validate-pilot, validate-other-change"
    assert found["tags"].detail == ("pilot: e2e-tests-pilot, storefront-pilot; "
                                    "other-change: e2e-tests-other-change, "
                                    "storefront-other-change")
    assert found["scenario pods"].detail == (
        f"validate-pilot/{POD} on arkhai:e2e-tests-pilot, exit 0; "
        f"validate-other-change/{POD} on arkhai:e2e-tests-other-change, exit 0")
    assert found["untouched"].detail.count("one revision of arkhai-node-operator") == 2


def test_every_cluster_read_names_the_runs_context(tmp_path: Path) -> None:
    fake = Fake(tmp_path)

    fake.report()

    cluster = [read for read in fake.reads if read[0] in ("kubectl", "helm")]
    assert cluster and all(read[1:3] == ["--context", "docker-desktop"] for read in cluster
                           if read[0] == "kubectl")
    assert all("--kube-context" in read for read in cluster if read[0] == "helm")


def test_each_runs_end_is_taken_as_it_ends(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.ends_last = FIRST

    fake.report()

    first, second = fake.validation.runs
    assert second.ended < first.ended
    assert fake.events[2:] == ["wait other-change", "wait pilot"]


def test_a_run_that_cannot_start_is_reported_beside_the_other(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.cannot_start = {SECOND}

    found = _checks(fake.report())

    first, second = fake.validation.runs
    assert first.status == 0 and second.status == 127
    assert not found["results"].passed
    assert ("other-change exited 127 with no summary; its log ends:\n"
            "| ERROR: could not start: [Errno 2] No such file or directory: 'make'"
            ) in found["results"].detail
    assert found["untouched"].detail == (
        "validate-pilot: one revision of arkhai-node-operator, its volumes and pods made "
        "during its own run on its own images, workloads at zero; "
        "validate-other-change: not judged, since its own Helm part did not pass")
    assert not found["untouched"].passed


def test_both_runs_start_before_either_is_waited_for(tmp_path: Path) -> None:
    fake = Fake(tmp_path)

    fake.report()

    assert fake.events[:2] == ["launch pilot", "launch other-change"]
    assert sorted(fake.events[2:]) == ["wait other-change", "wait pilot"]
    assert [(command, cwd) for command, cwd, _ in fake.launched] == [
        (["make", "-C", str(fake.clones[change]), "validate-helm", f"CHANGE={change}",
          "HELM_CONTEXT=docker-desktop"], fake.clones[change]) for change in (FIRST, SECOND)]


def test_the_report_and_each_runs_log_are_kept_beside_each_other(tmp_path: Path) -> None:
    fake = Fake(tmp_path)

    report = fake.report()

    directory = fake.root / check.LOG_ROOT / "20261021T190000Z"
    assert fake.validation.directory == directory
    assert sorted(path.name for path in directory.iterdir()) == [
        "other-change.log", "pilot.log", "report.json"]
    written = json.loads((directory / "report.json").read_text("utf-8"))
    assert written["passed"] is True
    assert [run["namespace"] for run in written["runs"]] == [
        "validate-pilot", "validate-other-change"]
    assert [entry["name"] for entry in written["checks"]] == [c.name for c in report.checks]


def test_scenario_pods_that_ran_apart_are_said_to(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[SECOND] = Namespace(SECOND, (26, 28))

    found = _checks(fake.report())

    assert found["together"].passed
    assert "their scenario pods ran one after the other" in found["together"].detail


# What a namespace can hold of its release after both runs that its own run did
# not leave: the other run's touch, or an earlier run's leftovers.

def _upgraded_again(state: Namespace) -> None:
    state.history.append({"revision": 5, "updated": _stamp(12),
                          "description": "Upgrade complete"})


def _its_pod_on_the_others_images(state: Namespace) -> None:
    state.pods.append(_pod(f"{RELEASE}-storefront-bob-2", state.name,
                           ["arkhai:storefront-pilot"]))


def _a_volume_deleted(state: Namespace) -> None:
    state.volumes = [volume for volume in state.volumes
                     if volume["metadata"]["name"] != f"{RELEASE}-storefront-data"]


def _scaled_up_again(state: Namespace) -> None:
    state.workloads[0]["spec"]["replicas"] = 1


def _a_pod_made_after_its_run(state: Namespace) -> None:
    state.pods.append(_pod(f"{RELEASE}-registry-1", state.name, ["arkhai:registry-other-change"],
                           minutes=45))


def _a_volume_made_before_the_check(state: Namespace) -> None:
    state.volumes[1]["metadata"]["creationTimestamp"] = _stamp(-60)


@pytest.mark.parametrize(("touch", "named"), [
    (_upgraded_again, "2 revisions of arkhai-node-operator since the check started"),
    (_its_pod_on_the_others_images, "pod arkhai-node-operator-storefront-bob-2 runs "
                                    "arkhai:storefront-pilot, not its own images"),
    (_a_volume_deleted, "arkhai-node-operator-storefront-data, which its pods mounted, "
                        "no longer exist"),
    (_scaled_up_again, "Deployment/arkhai-node-operator-storefront-bob up after its run "
                       "ended"),
    (_a_pod_made_after_its_run, "pod arkhai-node-operator-registry-1 was created at "
                                "2026-10-21T19:45:00Z, outside its run"),
    (_a_volume_made_before_the_check, "volume arkhai-buyer-profiles was created at "
                                      "2026-10-21T18:00:00Z, outside its run"),
])
def test_a_namespace_holding_what_its_run_did_not_leave_fails(tmp_path: Path, touch,
                                                              named) -> None:
    fake = Fake(tmp_path)
    touch(fake.namespaces[SECOND])

    report = fake.report()

    found = _checks(report)
    assert not report.passed
    assert not found["untouched"].passed
    assert f"validate-other-change: {named}" in found["untouched"].detail
    assert "validate-pilot: one revision" in found["untouched"].detail
    assert [name for name, result in found.items() if not result.passed] == ["untouched"]


@pytest.mark.parametrize(("break_it", "named"), [
    (lambda fake: fake.unreadable.add("helm history arkhai-node-operator --kube-context "
                                      "docker-desktop --namespace validate-other-change"),
     "validate-other-change: could not be read: helm history"),
    (lambda fake: setattr(fake.namespaces[SECOND], "history", {"revision": 4}),
     "validate-other-change: could not be read: helm history of arkhai-node-operator is "
     "not a list"),
    (lambda fake: fake.unreadable.add("print-RELEASE CHANGE=other-change"),
     "validate-other-change: could not be read: its release could not be read from"),
])
def test_a_namespace_that_cannot_be_read_fails_its_check_alone(tmp_path: Path, break_it,
                                                              named) -> None:
    fake = Fake(tmp_path)
    break_it(fake)

    found = _checks(fake.report())

    assert not found["untouched"].passed
    assert found["untouched"].detail.startswith(named)
    assert "validate-pilot: one revision of arkhai-node-operator" in found["untouched"].detail
    assert [name for name, result in found.items() if not result.passed] == ["untouched"]


@pytest.mark.parametrize(("kept_text", "named", "failing"), [
    ("not json", "pods.json could not be read", {"tags", "untouched"}),
    (json.dumps({"items": ["not a pod"]}), "pods.json holds an item that is not a pod",
     {"tags", "untouched"}),
    # `untouched` reads the kept pods for their claims alone, which this one has none of.
    (json.dumps({"items": [{"metadata": {"name": "p"}, "spec": {"containers": [
        {"image": None}]}}]}), "None is not an image name", {"tags"}),
])
def test_malformed_kept_pod_statuses_fail_the_checks_that_read_them(
        tmp_path: Path, kept_text, named, failing) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[SECOND].kept_text = kept_text

    found = _checks(fake.report())

    assert named in found["tags"].detail
    if "untouched" in failing:
        assert "validate-other-change: could not be read:" in found["untouched"].detail
    assert {name for name, result in found.items() if not result.passed} == failing


def test_another_releases_objects_in_the_namespace_are_not_judged(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    state = fake.namespaces[SECOND]
    state.pods.append(_pod("other-release-web-1", state.name, ["arkhai:storefront"],
                           minutes=-60, release="other-release"))
    state.volumes.append({"metadata": {"name": "other-release-data",
                                       "creationTimestamp": _stamp(-60),
                                       "labels": {"app.kubernetes.io/instance": "other-release"}}})
    state.workloads.append({"kind": "Deployment",
                            "metadata": {"name": "other-release-web",
                                         "labels": {"app.kubernetes.io/instance": "other-release"}},
                            "spec": {"replicas": 1}})

    report = fake.report()

    assert report.passed, check.render(report)


def test_a_summary_that_is_not_a_mapping_is_no_summary(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[SECOND].summary = ["not", "a", "summary"]

    found = _checks(fake.report())

    assert not found["results"].passed
    assert "other-change exited 0 with no summary" in found["results"].detail


def test_overlays_sharing_a_tag_fail(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[SECOND].overlay["registry"] = {"image": {"tag": "storefront-pilot"}}

    found = _checks(fake.report())

    assert not found["tags"].passed
    assert "both overlays name storefront-pilot" in found["tags"].detail


def test_a_pod_that_ran_another_tag_fails(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[FIRST].kept.append(_pod(f"{RELEASE}-registry-1", "validate-pilot",
                                            ["arkhai:registry"]))

    found = _checks(fake.report())

    assert not found["tags"].passed
    assert "pilot's pods ran registry, outside its own overlay" in found["tags"].detail


def test_a_run_kept_no_pod_statuses_shows_no_tag(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[FIRST].kept = []

    found = _checks(fake.report())

    assert not found["tags"].passed
    assert "pilot's kept pod statuses show no image built here" in found["tags"].detail


def test_a_run_in_another_namespace_fails(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[SECOND].summary_namespace = "default"

    found = _checks(fake.report())

    assert not found["namespaces"].passed
    assert found["namespaces"].detail == ("other-change ran in 'default', not "
                                          "validate-other-change")


def test_a_failed_part_is_named_with_its_failed_steps(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[FIRST].status, fake.namespaces[FIRST].passed = 1, False

    found = _checks(fake.report())

    assert not found["results"].passed
    assert found["results"].detail.splitlines()[0] == (
        f"pilot failed at e2e, in {ATTEMPT}")


def test_a_part_that_wrote_no_summary_is_named_with_its_logs_end(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    state = fake.namespaces[FIRST]
    state.status, state.passed, state.summary_namespace = 1, False, None

    found = _checks(fake.report())

    assert not found["results"].passed
    assert ("pilot exited 1 with no summary; its log ends:\n"
            "| ERROR: the Docker daemon is not reachable") in found["results"].detail


def test_a_scenario_pod_that_failed_or_is_gone_fails(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[FIRST].scenario["status"]["containerStatuses"][0]["state"][
        "terminated"]["exitCode"] = 1
    fake.unreadable = {f"get pod {POD} --namespace validate-other-change"}

    found = _checks(fake.report())

    assert not found["scenario pods"].passed
    assert f"pilot's scenario pod {POD} exited 1" in found["scenario pods"].detail
    assert "other-change: kubectl --context docker-desktop get pod" in found[
        "scenario pods"].detail
    assert "could not both be read" in found["together"].detail


def test_a_scenario_pod_with_no_status_fails_without_ending_the_report(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[FIRST].scenario["status"] = None

    found = _checks(fake.report())

    assert not found["scenario pods"].passed
    assert f"pilot's scenario pod {POD} exited None" in found["scenario pods"].detail
    assert "could not both be read" in found["together"].detail


def test_a_scenario_pod_on_the_others_image_fails(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    fake.namespaces[SECOND].scenario["spec"]["containers"][0]["image"] = "arkhai:e2e-tests-pilot"

    found = _checks(fake.report())

    assert not found["scenario pods"].passed
    assert (f"other-change's scenario pod {POD} ran arkhai:e2e-tests-pilot, not its own"
            in found["scenario pods"].detail)


@pytest.mark.parametrize(("clones", "located", "message"), [
    (["a"], None, "two clones are needed, not 1"),
    (["a", "b"], {"a": "pilot", "b": "pilot"}, "both clones are of pilot"),
    (["a", "b"], {"a": "pilot", "b": "Not_A_Change"}, "is not a change name"),
])
def test_the_check_refuses_two_changes_it_cannot_tell_apart(tmp_path: Path, clones, located,
                                                            message) -> None:
    with pytest.raises((check.CheckError, ValueError), match=message):
        check.ParallelValidation([tmp_path / name for name in clones], root=tmp_path,
                                 read=lambda command: "",
                                 locate=lambda clone: (located or {})[clone.name])


def test_the_command_line_refuses_one_clone(capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main(["somewhere"]) == 2
    assert "two clones are needed, not 1" in capsys.readouterr().err


def test_the_command_line_refuses_a_clone_that_does_not_exist(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main([str(tmp_path / "no-such-clone"), str(tmp_path / "nor-this")]) == 2
    assert capsys.readouterr().err.startswith("ERROR: ")


@pytest.mark.parametrize(("text", "expected"), [
    ("2026-10-21T19:06:00Z", datetime(2026, 10, 21, 19, 6, tzinfo=timezone.utc)),
    ("2026-10-21T19:06:00.123456789Z",
     datetime(2026, 10, 21, 19, 6, 0, 123456, tzinfo=timezone.utc)),
    ("2026-10-21T21:06:00.5+02:00",
     datetime(2026, 10, 21, 19, 6, 0, 500000, tzinfo=timezone.utc)),
])
def test_kubernetes_and_helm_times_are_read(text: str, expected: datetime) -> None:
    assert check.parse_time(text) == expected


def test_a_time_that_is_not_one_is_refused() -> None:
    with pytest.raises(ValueError, match="is not a timestamp"):
        check.parse_time("yesterday")


def test_the_runs_read_neither_the_checks_make_variables_nor_a_change(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAKEFLAGS", " -- CLONES=a b")
    monkeypatch.setenv("CHANGE", "a-step-change")
    monkeypatch.setenv("HOME", str(tmp_path))
    log = tmp_path / "run.log"

    status = check._launch([sys.executable, "-c", "import os; print(sorted(k for k in "
                            "('MAKEFLAGS', 'CHANGE', 'HOME') if k in os.environ))"],
                           tmp_path, log).wait()

    assert status == 0
    assert log.read_text("utf-8").strip() == "['HOME']"


def test_the_make_target_runs_the_check_over_its_clones() -> None:
    environment = {name: value for name, value in os.environ.items()
                   if name not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "CHANGE")}

    printed = subprocess.run(["make", "-n", "-s", "--no-print-directory", "validate-parallel",
                              "CLONES=../a ../b", "HELM_CONTEXT=kind-test"], cwd=REPO_ROOT,
                             env=environment, capture_output=True, text=True, check=True).stdout

    assert printed.strip() == ("python3 scripts/validate_parallel.py --context "
                               "\"kind-test\" ../a ../b")


# Which change a clone is of, read from a real clone in a temporary directory.

def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".gitignore").write_text(".claude/settings.local.json\n", "utf-8")
    _git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(tmp_path / "origin.git"))
    _git(work, "init", "-q", "-b", "dev")
    _git(work, "add", "--all")
    _git(work, "commit", "-q", "-m", "dev")
    _git(work, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _git(work, "push", "-q", "origin", "dev")
    return work


def _spawned(status: str):
    def spawn(command, cwd: Path, log: Path, status_file: Path) -> int:
        status_file.write_text(status + "\n", "utf-8")
        return os.getpid()
    return spawn


def test_a_clone_whose_bootstrap_succeeded_is_of_its_change(workspace: Path) -> None:
    clone = change_clone.create(workspace, FIRST, spawn=_spawned("0")).clone

    assert check.change_of(clone) == FIRST


def test_a_clone_whose_bootstrap_failed_is_refused_naming_its_log(workspace: Path) -> None:
    clone = change_clone.create(workspace, FIRST, spawn=_spawned("2")).clone

    with pytest.raises(check.CheckError, match="bootstrap is failed; its log is .*"
                                               "change-bootstrap.log"):
        check.change_of(clone)


def test_a_clone_with_another_branch_checked_out_is_refused(workspace: Path) -> None:
    clone = change_clone.create(workspace, FIRST, spawn=_spawned("0")).clone
    _git(clone, "checkout", "-q", "-b", "elsewhere")

    with pytest.raises(check.CheckError, match=f"is not .*clone of {FIRST} with that "
                                               "change's branch checked out"):
        check.change_of(clone)


def test_a_checkout_that_is_no_clone_is_refused(workspace: Path) -> None:
    with pytest.raises(check.CheckError, match="is not a change's clone"):
        check.change_of(workspace)
