"""Loading a release candidate, with every subprocess stubbed at the script's `run`.

`scripts/load_candidate.py` runs `make`, `docker` and `gcloud` through one `run`
seam, the process boundary it wraps. Each test drives a load over a synthetic
tree, whose declaration, projects and wheelhouse are real files, through a stub
standing in for those processes: the build writes the chart's package and the
binary, and `docker image inspect` answers each image's labels. What the load
then deletes, uploads and pushes is read from the commands it ran.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from load_candidate import main
from release_components import REPO_ROOT
from wheelhouse_digest import LABEL, wheelhouse_digest

REVISION = "0123456ab"
REGISTRY = "region-docker.pkg.dev/project/prefix-docker"
ARGUMENTS = ["--project", "project", "--location", "region", "--prefix", "prefix",
             "--docker-registry", REGISTRY, "--revision", REVISION]
DECLARATION = {
    "distributions": [
        {"key": "core", "path": "core", "dist": "arkhai-core"},
        {"key": "core-buyer", "path": "core/buyer", "dist": "arkhai-core-buyer"},
    ],
    "images": [
        {"name": "registry", "local": "registry"},
        {"name": "provisioning", "local": "compute-provisioning"},
        {"name": "frp-grant-admission", "local": "frp-grant-admission"},
    ],
    "chart": {"path": "helm"},
    "binaries": [{"name": "market", "target": "build-market-binary",
                  "path": ".dist/bin/market"}],
    "development_images": [{"name": "dev-env", "local": "dev-env"}],
}
WHEELS = ("arkhai_core-1.0.0-py3-none-any.whl", "arkhai_core_buyer-1.0.0-py3-none-any.whl")
CHART = ".dist/arkhai-node-operator-0.4.1.tgz"
# The images whose builds install from the wheelhouse, and so carry its digest.
FROM_WHEELHOUSE = ("registry", "compute-provisioning")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "release-components.json").write_text(
        json.dumps(DECLARATION), encoding="utf-8")
    for entry in DECLARATION["distributions"]:
        (tmp_path / entry["path"]).mkdir(parents=True, exist_ok=True)
        (tmp_path / entry["path"] / "pyproject.toml").write_text(
            f'[project]\nname = "{entry["dist"]}"\nversion = "1.0.0"\n', encoding="utf-8")
    (tmp_path / "helm").mkdir()
    (tmp_path / "helm" / "Chart.yaml").write_text(
        "apiVersion: v2\nname: arkhai-node-operator\nversion: 0.4.1\n", encoding="utf-8")
    (tmp_path / ".dist").mkdir()
    for wheel in WHEELS:
        (tmp_path / ".dist" / wheel).write_bytes(f"the bytes of {wheel}".encode())
    # A wheel only tests install, which the store never receives.
    (tmp_path / ".dist" / "lane_double_controls-0.1.0-py3-none-any.whl").write_bytes(b"test")
    return tmp_path


class Processes:
    """The processes the load runs. The build writes the chart's package and the
    binary and labels each image built from the wheelhouse with its digest;
    `labels` overrides an image's labels, `failing` makes the first command
    starting with it fail, and a delete answers `delete_error`, or succeeds when
    it is None, as for a revision loaded before; removing a revision tag answers
    `untag_error` the same way, as for a revision built before."""

    def __init__(self, root: Path, labels: dict[str, dict[str, str] | None] | None = None,
                 failing: tuple[str, ...] | None = None, on_build=None,
                 delete_error: str | None = "NOT_FOUND: no such version",
                 untag_error: str | None = "Error response from daemon: No such image") -> None:
        self.root, self.overrides, self.failing = root, labels or {}, failing
        self.on_build, self.delete_error, self.untag_error = on_build, delete_error, untag_error
        self.commands: list[list[str]] = []
        self.labels: dict[str, dict[str, str] | None] = {}

    def __call__(self, command: list[str], **kwargs) -> subprocess.CompletedProcess:
        command = [str(word) for word in command]
        self.commands.append(command)
        if self.failing and tuple(command[:len(self.failing)]) == self.failing:
            raise subprocess.CalledProcessError(2, command)
        if command[:3] == ["make", "--no-print-directory", "build-candidate"]:
            digest = wheelhouse_digest(self.root)
            (self.root / CHART).write_bytes(b"chart")
            (self.root / ".dist" / "bin").mkdir(exist_ok=True)
            (self.root / ".dist" / "bin" / "market").write_bytes(b"binary")
            for image in (*DECLARATION["images"], *DECLARATION["development_images"]):
                local = image["local"]
                self.labels[local] = ({LABEL: digest} if local in FROM_WHEELHOUSE else {})
            self.labels.update(self.overrides)
            if self.on_build:
                self.on_build(self.root)
        if command[:3] == ["docker", "image", "inspect"]:
            local = command[-1].removeprefix("arkhai:").removesuffix(f"-{REVISION}")
            labels = self.labels.get(local)
            if labels is None:
                return subprocess.CompletedProcess(command, 1, "", "No such image")
            return subprocess.CompletedProcess(command, 0, json.dumps(labels or None), "")
        if command[:3] == ["docker", "image", "rm"]:
            if self.untag_error is None:
                return subprocess.CompletedProcess(command, 0, f"Untagged: {command[-1]}", "")
            return subprocess.CompletedProcess(command, 1, "", self.untag_error)
        if command[:4] == ["gcloud", "artifacts", "versions", "delete"]:
            if self.delete_error is None:
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 1, "", self.delete_error)
        return subprocess.CompletedProcess(command, 0, "", "")

    def index(self, prefix: list[str]) -> int:
        return next(i for i, command in enumerate(self.commands)
                    if command[:len(prefix)] == prefix)

    def matching(self, prefix: list[str]) -> list[list[str]]:
        return [command for command in self.commands if command[:len(prefix)] == prefix]

    def uploaded(self) -> bool:
        return bool(self.matching(["gcloud", "artifacts", "generic", "upload"])
                    or self.matching(["docker", "push"])
                    or self.matching(["gcloud", "artifacts", "versions", "delete"]))


def _flag(command: list[str], name: str) -> str:
    return next(word.split("=", 1)[1] for word in command if word.startswith(f"--{name}="))


def test_a_load_builds_checks_deletes_and_then_uploads_in_order(root: Path) -> None:
    processes = Processes(root)

    assert main(ARGUMENTS, run=processes, root=root) == 0

    make = ["make", "--no-print-directory"]
    locals_ = [image["local"] for image in (*DECLARATION["images"],
                                            *DECLARATION["development_images"])]
    assert processes.commands[:7] == [
        [*make, "dist", "IMAGE_SUFFIX="],
        [*make, "check-release-versions", "IMAGE_SUFFIX="],
        *[["docker", "image", "rm", f"arkhai:{local}-{REVISION}"] for local in locals_],
        [*make, "build-candidate", "IMAGE_SUFFIX="]]
    inspects = [i for i, c in enumerate(processes.commands) if c[:3] == ["docker", "image",
                                                                          "inspect"]]
    deletes = processes.matching(["gcloud", "artifacts", "versions", "delete"])
    assert [(_flag(c, "repository"), _flag(c, "package")) for c in deletes] == [
        ("prefix-candidates", "wheelhouse"), ("prefix-candidates", "chart"),
        ("prefix-cli", "market")]
    assert all(command[4] == REVISION for command in deletes)
    delete_indices = [i for i, c in enumerate(processes.commands) if c in deletes]
    uploads = [i for i, c in enumerate(processes.commands)
               if c[:4] == ["gcloud", "artifacts", "generic", "upload"]]
    pushes = [i for i, c in enumerate(processes.commands) if c[:2] == ["docker", "push"]]
    assert max(inspects) < min(delete_indices)
    assert max(delete_indices) < min(uploads)
    assert max(uploads) < min(pushes)


def test_the_store_receives_exactly_the_declared_wheels_one_chart_and_one_binary(
        root: Path) -> None:
    processes = Processes(root)

    main(ARGUMENTS, run=processes, root=root)

    uploads = [(_flag(c, "repository"), _flag(c, "package"), _flag(c, "version"),
                _flag(c, "source"))
               for c in processes.matching(["gcloud", "artifacts", "generic", "upload"])]
    assert uploads == [
        *[("prefix-candidates", "wheelhouse", REVISION, str(root / ".dist" / wheel))
          for wheel in WHEELS],
        ("prefix-candidates", "chart", REVISION, str(root / CHART)),
        ("prefix-cli", "market", REVISION, str(root / ".dist" / "bin" / "market")),
    ]


def test_every_declared_image_and_development_image_is_pushed_under_the_revision(
        root: Path) -> None:
    processes = Processes(root)

    main(ARGUMENTS, run=processes, root=root)

    pushed = [command[2] for command in processes.matching(["docker", "push"])]
    names = [image["name"] for image in (*DECLARATION["images"],
                                         *DECLARATION["development_images"])]
    assert pushed == [tag for name in names for tag in (f"{REGISTRY}/arkhai:{name}-{REVISION}",
                                                        f"{REGISTRY}/arkhai:{name}")]
    assert ["docker", "tag", f"arkhai:compute-provisioning-{REVISION}",
            f"{REGISTRY}/arkhai:provisioning-{REVISION}"] in processes.commands


def test_no_command_keeps_an_earlier_file(root: Path) -> None:
    processes = Processes(root)

    main(ARGUMENTS, run=processes, root=root)

    assert not any(word.startswith("--skip-existing") for command in processes.commands
                   for word in command)


def test_a_wheelhouse_changed_after_the_image_builds_uploads_nothing(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def rebuild_a_wheel(tree: Path) -> None:
        (tree / ".dist" / WHEELS[0]).write_bytes(b"other bytes")
    processes = Processes(root, on_build=rebuild_a_wheel)

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert not processes.uploaded()
    error = capsys.readouterr().err
    assert "uploaded nothing" in error
    assert f"the wheelhouse {root / '.dist'} changed while the load built from it" in error


def test_an_image_built_from_another_wheelhouse_uploads_nothing(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    processes = Processes(root, labels={"registry": {LABEL: "0" * 64}})

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert not processes.uploaded()
    assert (f"arkhai:registry-{REVISION} was built from another wheelhouse: its {LABEL} is "
            + "0" * 64) in capsys.readouterr().err


def test_an_image_labelled_with_an_empty_digest_uploads_nothing(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    processes = Processes(root, labels={"compute-provisioning": {LABEL: ""}})

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert not processes.uploaded()
    assert f"arkhai:compute-provisioning-{REVISION} was built from another wheelhouse: " \
           f"its {LABEL} is (empty)" in capsys.readouterr().err


def test_a_declared_image_the_build_did_not_write_uploads_nothing(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    processes = Processes(root, labels={"dev-env": None})

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert not processes.uploaded()
    assert f"arkhai:dev-env-{REVISION} was not built" in capsys.readouterr().err


def test_a_revision_tag_an_earlier_build_left_is_removed_before_the_build(root: Path) -> None:
    """With the earlier tag removed, an image this load's build does not write is
    missing afterwards rather than passing as the earlier build's."""
    processes = Processes(root, untag_error=None, labels={"registry": None})

    assert main(ARGUMENTS, run=processes, root=root) == 1

    untagged = processes.index(["docker", "image", "rm", f"arkhai:registry-{REVISION}"])
    assert untagged < processes.index(["make", "--no-print-directory", "build-candidate"])
    assert not processes.uploaded()


def test_a_revision_tag_that_cannot_be_removed_stops_the_load_before_the_build(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    processes = Processes(root, untag_error="conflict: unable to remove repository reference")

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert not processes.matching(["make", "--no-print-directory", "build-candidate"])
    assert not processes.uploaded()
    assert f"cannot remove the earlier arkhai:registry-{REVISION}" in capsys.readouterr().err


def test_a_chart_package_or_binary_the_build_did_not_write_uploads_nothing(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def lose_both(tree: Path) -> None:
        (tree / CHART).unlink()
        (tree / ".dist" / "bin" / "market").unlink()
    processes = Processes(root, on_build=lose_both)

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert not processes.uploaded()
    error = capsys.readouterr().err
    assert f"the chart's package {root / CHART} was not built" in error
    assert "the binary market was not built at .dist/bin/market" in error


def test_a_version_check_failure_stops_the_load_before_any_build(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    processes = Processes(root, failing=("make", "--no-print-directory",
                                         "check-release-versions"))

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert not processes.matching(["make", "--no-print-directory", "build-candidate"])
    assert not processes.uploaded()
    assert "check-release-versions IMAGE_SUFFIX= failed with exit status 2" in (
        capsys.readouterr().err)


def test_a_reload_deletes_the_revisions_stored_versions_before_uploading(root: Path) -> None:
    """A revision loaded before holds its versions, which the deletes remove."""
    processes = Processes(root, delete_error=None)

    assert main(ARGUMENTS, run=processes, root=root) == 0

    assert len(processes.matching(["gcloud", "artifacts", "versions", "delete"])) == 3
    assert len(processes.matching(["gcloud", "artifacts", "generic", "upload"])) == 4


def test_a_delete_refused_for_another_reason_uploads_nothing(
        root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    processes = Processes(root, delete_error="PERMISSION_DENIED: no")

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert not processes.matching(["gcloud", "artifacts", "generic", "upload"])
    assert "cannot delete wheelhouse 0123456ab from prefix-candidates: PERMISSION_DENIED" in (
        capsys.readouterr().err)


def test_an_upload_failing_after_the_deletes_stops_the_load(root: Path) -> None:
    processes = Processes(root, failing=("gcloud", "artifacts", "generic", "upload"))

    assert main(ARGUMENTS, run=processes, root=root) == 1

    assert len(processes.matching(["gcloud", "artifacts", "versions", "delete"])) == 3
    assert len(processes.matching(["gcloud", "artifacts", "generic", "upload"])) == 1
    assert not processes.matching(["docker", "push"])


def test_make_passes_the_load_its_destination_and_nine_character_revision() -> None:
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL")}
    printed = subprocess.run(
        ["make", "-n", "--no-print-directory", "load-candidate", "AR_PROJECT=project",
         "AR_LOCATION=region"], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        env=environment).stdout
    line = next(line for line in printed.replace("\\\n", " ").splitlines()
                if "scripts/load_candidate.py" in line)
    words = shlex.split(line)
    values = dict(zip(words[2::2], words[3::2]))
    revision = subprocess.run(["git", "rev-parse", "--short=9", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()

    assert values == {"--project": "project", "--location": "region", "--prefix": "project",
                      "--docker-registry": "region-docker.pkg.dev/project/project-docker",
                      "--revision": revision}
    assert len(revision) == 9
