"""Running a release candidate's images in the local lanes, and recording them.

`scripts/release_images.py` runs `docker` through one `run` seam, the process
boundary it wraps. Its commands are driven over a synthetic declaration through a
stub standing in for `docker`: `docker compose config --images` answers the
lane's images, `docker image inspect` whether a tag is present and its repo
digests, and `docker compose ps` and `docker container inspect` the lane's running
containers.

The lane targets are read through `make -n`, and the lanes' Compose files are
rendered with the real `docker compose config`. Those renders skip without Docker
Compose, except under `COMPOSE_REQUIRED=1`, which CI's packaging job sets, where a
skip is a failure.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest

from release_components import REPO_ROOT, load
from release_images import main, record_path

SUFFIX = "-0123456ab"
# A placeholder registry, naming no real project.
REGISTRY = "region-docker.pkg.dev/project/prefix-docker"
COMPOSE = "-p lane -f compose.lane.yml"
DECLARATION = {
    "distributions": [{"key": "core", "path": "core", "dist": "arkhai-core"}],
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
REGISTRY_DIGEST = "sha256:" + "1" * 64
PROVISIONING_DIGEST = "sha256:" + "2" * 64


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "release-components.json").write_text(
        json.dumps(DECLARATION), encoding="utf-8")
    return tmp_path


class Docker:
    """The `docker` the script runs. `referenced` is what the lane's Compose files
    run, `present` the local tags, `containers` each running container's image
    reference and image ID, and `repo_digests` each image ID's repo digests;
    `failing` makes the first command starting with it fail, and `inspect_error`
    is what inspecting a tag that is not present answers."""

    def __init__(self, referenced=(), present=(), containers=(), repo_digests=None,
                 failing: tuple[str, ...] | None = None,
                 inspect_error: str = "Error response from daemon: No such image") -> None:
        self.referenced, self.present = list(referenced), set(present)
        self.containers = list(containers)
        self.repo_digests = repo_digests or {}
        self.failing, self.inspect_error = failing, inspect_error
        self.commands: list[list[str]] = []
        self.compose_calls: list[dict] = []

    def __call__(self, command: list[str], **kwargs) -> subprocess.CompletedProcess:
        command = [str(word) for word in command]
        self.commands.append(command)
        if self.failing and tuple(command[:len(self.failing)]) == self.failing:
            raise subprocess.CalledProcessError(1, command, "", "manifest unknown")
        if command[:2] == ["docker", "compose"]:
            self.compose_calls.append({"command": command, "cwd": kwargs.get("cwd"),
                                       "suffix": kwargs["env"].get("IMAGE_SUFFIX")})
            if command[-2:] == ["config", "--images"]:
                return subprocess.CompletedProcess(command, 0, "\n".join(self.referenced) + "\n")
            if command[-2:] == ["ps", "--quiet"]:
                ids = "\n".join(f"container{index}" for index in range(len(self.containers)))
                return subprocess.CompletedProcess(command, 0, ids + "\n")
        if command[:3] == ["docker", "container", "inspect"]:
            return subprocess.CompletedProcess(command, 0, json.dumps([
                {"Id": name, "Config": {"Image": self.containers[int(name[9:])][0]},
                 "Image": self.containers[int(name[9:])][1]} for name in command[3:]]))
        if command[:3] == ["docker", "image", "inspect"] and len(command) == 4 \
                and command[3].startswith("arkhai:"):
            present = command[3] in self.present
            return subprocess.CompletedProcess(command, 0 if present else 1, "[]",
                                               "" if present else self.inspect_error)
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, json.dumps([
                {"Id": image_id, "RepoDigests": self.repo_digests.get(image_id)}
                for image_id in command[3:]]))
        return subprocess.CompletedProcess(command, 0, "", "")


# --- pull ----------------------------------------------------------------------


def test_pull_takes_each_release_image_by_its_published_name_and_tags_it_locally(
        root: Path) -> None:
    docker = Docker()

    assert main(["pull", "--registry", REGISTRY, f"--suffix={SUFFIX}"], run=docker,
                root=root) == 0

    assert docker.commands == [
        ["docker", "pull", f"{REGISTRY}/arkhai:registry{SUFFIX}"],
        ["docker", "tag", f"{REGISTRY}/arkhai:registry{SUFFIX}", f"arkhai:registry{SUFFIX}"],
        ["docker", "pull", f"{REGISTRY}/arkhai:provisioning{SUFFIX}"],
        ["docker", "tag", f"{REGISTRY}/arkhai:provisioning{SUFFIX}",
         f"arkhai:compute-provisioning{SUFFIX}"],
        ["docker", "pull", f"{REGISTRY}/arkhai:frp-grant-admission{SUFFIX}"],
        ["docker", "tag", f"{REGISTRY}/arkhai:frp-grant-admission{SUFFIX}",
         f"arkhai:frp-grant-admission{SUFFIX}"],
    ]


def test_a_failed_pull_stops_and_is_named(root: Path, capsys) -> None:
    docker = Docker(failing=("docker", "pull", f"{REGISTRY}/arkhai:provisioning{SUFFIX}"))

    assert main(["pull", "--registry", REGISTRY, f"--suffix={SUFFIX}"], run=docker,
                root=root) == 1

    assert docker.commands[-1][:2] == ["docker", "pull"]
    error = capsys.readouterr().err
    assert f"docker pull {REGISTRY}/arkhai:provisioning{SUFFIX} failed" in error
    assert "manifest unknown" in error


@pytest.mark.parametrize("arguments", [
    ["pull", "--registry", REGISTRY, "--suffix="],
    ["pull", "--registry=", f"--suffix={SUFFIX}"],
    ["check", f"--compose={COMPOSE}", "--suffix="],
    ["record", "--lane", "vm", f"--compose={COMPOSE}", "--suffix="],
], ids=["pull without a suffix", "pull without a registry", "check without a suffix",
        "record without a suffix"])
def test_an_empty_suffix_or_registry_is_refused_with_nothing_run(
        root: Path, arguments: list[str], capsys) -> None:
    docker = Docker()

    with pytest.raises(SystemExit) as refused:
        main(arguments, run=docker, root=root)

    assert refused.value.code == 2
    assert docker.commands == []
    assert "is required" in capsys.readouterr().err


# --- check ---------------------------------------------------------------------


def test_check_passes_when_every_release_image_the_lane_runs_is_present(
        root: Path, capsys) -> None:
    docker = Docker(referenced=[f"arkhai:registry{SUFFIX}", f"arkhai:compute-provisioning{SUFFIX}",
                                "arkhai:dev-env", "arkhai:payments-lane-double"],
                    present=[f"arkhai:registry{SUFFIX}", f"arkhai:compute-provisioning{SUFFIX}"])

    assert main(["check", f"--compose={COMPOSE}", f"--suffix={SUFFIX}"], run=docker, root=root) == 0

    assert "OK" in capsys.readouterr().out
    # The lane's files are rendered from the repository root with the candidate's
    # suffix, as the lane's own Compose commands see them.
    assert docker.compose_calls == [{"command": ["docker", "compose", "-p", "lane", "-f",
                                                 "compose.lane.yml", "config", "--images"],
                                     "cwd": root, "suffix": SUFFIX}]
    # A release image the lane does not run, and an image that is not a release
    # image, are not looked for.
    inspected = [command[3] for command in docker.commands if command[:3] == [
        "docker", "image", "inspect"]]
    assert inspected == [f"arkhai:registry{SUFFIX}", f"arkhai:compute-provisioning{SUFFIX}"]


def test_check_names_every_release_image_the_lane_runs_that_is_missing(
        root: Path, capsys) -> None:
    docker = Docker(referenced=[f"arkhai:registry{SUFFIX}", f"arkhai:compute-provisioning{SUFFIX}"])

    assert main(["check", f"--compose={COMPOSE}", f"--suffix={SUFFIX}"], run=docker, root=root) == 1

    error = capsys.readouterr().err
    assert f"arkhai:registry{SUFFIX} is not present locally" in error
    assert f"arkhai:compute-provisioning{SUFFIX} is not present locally" in error
    assert "pull-release-images" in error


def test_check_names_a_failed_inspection_as_itself_rather_than_as_a_missing_image(
        root: Path, capsys) -> None:
    docker = Docker(referenced=[f"arkhai:registry{SUFFIX}"],
                    inspect_error="Cannot connect to the Docker daemon")

    assert main(["check", f"--compose={COMPOSE}", f"--suffix={SUFFIX}"], run=docker,
                root=root) == 1

    error = capsys.readouterr().err
    assert f"cannot inspect arkhai:registry{SUFFIX}: Cannot connect to the Docker daemon" in error
    assert "not present locally" not in error


def test_check_refuses_a_release_image_the_lane_names_without_the_suffix(
        root: Path, capsys) -> None:
    docker = Docker(referenced=["arkhai:registry", f"arkhai:compute-provisioning{SUFFIX}"],
                    present=["arkhai:registry", f"arkhai:compute-provisioning{SUFFIX}"])

    assert main(["check", f"--compose={COMPOSE}", f"--suffix={SUFFIX}"], run=docker, root=root) == 1

    assert (f"run arkhai:registry rather than arkhai:registry{SUFFIX}: name it "
            "arkhai:registry${IMAGE_SUFFIX:-}") in capsys.readouterr().err


# --- record --------------------------------------------------------------------


def _running() -> Docker:
    """Two containers of one release image, as the VM lane's two registries are,
    one of another, and images that are not release images."""
    return Docker(
        referenced=[f"arkhai:registry{SUFFIX}", f"arkhai:compute-provisioning{SUFFIX}",
                    "arkhai:dev-env", "arkhai:payments-lane-double"],
        containers=[(f"arkhai:registry{SUFFIX}", "sha256:registry-image"),
                    (f"arkhai:registry{SUFFIX}", "sha256:registry-image"),
                    (f"arkhai:compute-provisioning{SUFFIX}", "sha256:provisioning-image"),
                    ("arkhai:dev-env", "sha256:dev-env-image"),
                    ("arkhai:payments-lane-double", "sha256:double-image")],
        repo_digests={
            # The local repository's digest, which an image store keeping images in
            # containerd adds for the local tag, names no registry and is not read.
            "sha256:registry-image": [f"{REGISTRY}/arkhai@{REGISTRY_DIGEST}",
                                      f"arkhai@{REGISTRY_DIGEST}"],
            # One manifest pulled through two registries is one digest.
            "sha256:provisioning-image": [f"{REGISTRY}/arkhai@{PROVISIONING_DIGEST}",
                                          f"localhost:5000/arkhai@{PROVISIONING_DIGEST}"],
        })


def test_record_names_each_release_image_running_by_its_published_name_and_manifest(
        root: Path, capsys) -> None:
    docker = _running()

    assert main(["record", "--lane", "bare-metal", f"--compose={COMPOSE}", f"--suffix={SUFFIX}"],
                run=docker, root=root) == 0

    expected = {"lane": "bare-metal", "image_suffix": SUFFIX,
                "images": {"registry": REGISTRY_DIGEST, "provisioning": PROVISIONING_DIGEST}}
    written = record_path(root, "bare-metal")
    assert written == root / ".snapshot" / "e2e-release-images-bare-metal.json"
    assert json.loads(written.read_text(encoding="utf-8")) == expected
    assert json.loads(capsys.readouterr().out) == expected
    # No registry's name reaches the record.
    assert REGISTRY not in written.read_text(encoding="utf-8")
    assert docker.compose_calls[0]["suffix"] == SUFFIX
    # Each image is inspected once, however many containers run it.
    images = [command for command in docker.commands if command[:3] == [
        "docker", "image", "inspect"]]
    assert images == [["docker", "image", "inspect", "sha256:provisioning-image",
                       "sha256:registry-image"]]


@pytest.mark.parametrize(("digests", "message"), [
    ([], f"arkhai:compute-provisioning{SUFFIX} has no repo digest from a registry"),
    # A locally built image, on an image store keeping images in containerd.
    ([f"arkhai@{PROVISIONING_DIGEST}"],
     f"arkhai:compute-provisioning{SUFFIX} has no repo digest from a registry"),
    ([f"{REGISTRY}/arkhai@{PROVISIONING_DIGEST}", f"localhost:5000/arkhai@{REGISTRY_DIGEST}"],
     f"arkhai:compute-provisioning{SUFFIX} has repo digests {REGISTRY_DIGEST}, "
     f"{PROVISIONING_DIGEST}"),
], ids=["no repo digest", "only the local repository's", "two repo digests"])
def test_record_refuses_an_image_without_exactly_one_manifest_and_writes_nothing(
        root: Path, digests: list[str], message: str, capsys) -> None:
    docker = _running()
    docker.repo_digests["sha256:provisioning-image"] = digests

    assert main(["record", "--lane", "bare-metal", f"--compose={COMPOSE}", f"--suffix={SUFFIX}"],
                run=docker, root=root) == 1

    assert message in capsys.readouterr().err
    assert not record_path(root, "bare-metal").exists()


def test_record_refuses_a_release_image_the_lane_runs_with_no_running_container(
        root: Path, capsys) -> None:
    docker = _running()
    docker.referenced.append(f"arkhai:frp-grant-admission{SUFFIX}")

    assert main(["record", "--lane", "bare-metal", f"--compose={COMPOSE}", f"--suffix={SUFFIX}"],
                run=docker, root=root) == 1

    assert (f"the lane's Compose files run arkhai:frp-grant-admission{SUFFIX}, and no running "
            "container runs it") in capsys.readouterr().err
    assert not record_path(root, "bare-metal").exists()


def test_record_refuses_a_lane_running_no_release_image_of_the_candidate(
        root: Path, capsys) -> None:
    docker = Docker(containers=[("arkhai:registry", "sha256:built"),
                                ("arkhai:dev-env", "sha256:dev-env-image")])

    assert main(["record", "--lane", "vm", f"--compose={COMPOSE}", f"--suffix={SUFFIX}"],
                run=docker, root=root) == 1

    assert "no running container of the lane runs a release image" in capsys.readouterr().err
    assert not record_path(root, "vm").exists()


# --- the lane targets ----------------------------------------------------------


LANES = ("vm", "bare-metal", "apicredits")
_ENTERS = re.compile(r"^cd (\S+) && make (\S+)((?: [A-Z_]+=\S*)*)\s*$")
_BUILD_TAG = re.compile(r"\s-t (\S+)")
_DIRECTORY = re.compile(r"^make(?:\[\d+\])?: (Entering|Leaving) directory '(.+)'$")


def _environment() -> dict[str, str]:
    # A make running these tests passes its variables down through MAKEFLAGS.
    return {key: value for key, value in os.environ.items()
            if key not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL", "IMAGE_SUFFIX",
                           "RELEASE_IMAGES")}


def _make_n(directory: Path, *arguments: str) -> list[str]:
    printed = subprocess.run(["make", "-n", "--no-print-directory", *arguments],
                             cwd=directory, capture_output=True, text=True, check=True,
                             env=_environment()).stdout
    return re.sub(r"\\\n\s*", " ", printed).splitlines()


@cache
def lane_commands(lane: str, *variables: str) -> tuple[str, ...]:
    """Each command `make -C e2e-tests test-e2e-<lane>` runs, in order.

    `make -n` runs a `$(MAKE)` line as well as printing it, so the root build the
    lane enters with `cd .. && $(MAKE) build-e2e-<lane>` prints its commands in
    place, with the variables MAKEFLAGS passes it, inside the directory lines
    `-w` prints. A recipe entering a subproject with `cd <dir> && make <target>`
    is printed and not run, so the walk follows those from the directory make
    was in, with the variables the line passes, unless make ran it in place."""
    def walk(directory: Path, arguments: tuple[str, ...]) -> list[str]:
        printed = subprocess.run(["make", "-n", "-w", *arguments], cwd=directory,
                                 capture_output=True, text=True, check=True,
                                 env=_environment()).stdout
        lines = re.sub(r"\\\n\s*", " ", printed).splitlines()
        commands: list[str] = []
        directories = [directory]
        for index, line in enumerate(lines):
            moved = _DIRECTORY.match(line)
            if moved:
                if moved.group(1) == "Entering":
                    directories.append(Path(moved.group(2)))
                else:
                    directories.pop()
                continue
            entered = _ENTERS.match(line.strip())
            target = entered and (directories[-1] / entered.group(1)).resolve()
            following = _DIRECTORY.match(lines[index + 1]) if index + 1 < len(lines) else None
            ran_in_place = following is not None and Path(following.group(2)) == target
            if entered and (target / "Makefile").is_file() and not ran_in_place:
                commands += walk(target, (entered.group(2), *entered.group(3).split()))
            else:
                commands.append(line)
        return commands
    return tuple(walk(REPO_ROOT / "e2e-tests", (f"test-e2e-{lane}", *variables)))


def _release_tags() -> set[str]:
    return {f"arkhai:{image.local}" for image in load().images}


_TAG = re.compile(r"\bdocker tag (\S+) (\S+)")


def _built(commands: tuple[str, ...]) -> list[str]:
    """The tags each `docker build` writes, every `-t` of each."""
    return [tag for line in commands if "docker build" in line
            for tag in _BUILD_TAG.findall(line.split("docker build", 1)[1])]


def _written(commands: tuple[str, ...]) -> set[str]:
    """Every tag the commands write: each `docker build`'s and each `docker tag`'s."""
    return set(_built(commands)) | {tag for line in commands for _, tag in _TAG.findall(line)}


def _option(command: str, name: str) -> str:
    """The value `command` passes as `--<name>=<value>`."""
    [value] = [word.split("=", 1)[1] for word in shlex.split(command)
               if word.startswith(f"--{name}=")]
    return value


def _index(commands: tuple[str, ...], pattern: str) -> int:
    matches = [index for index, line in enumerate(commands) if re.search(pattern, line)]
    assert len(matches) == 1, f"{pattern!r} matches {len(matches)} commands"
    return matches[0]


@pytest.mark.parametrize("lane", LANES)
def test_a_lane_run_on_release_images_builds_none_and_checks_then_records_them(
        lane: str) -> None:
    commands = lane_commands(lane, "RELEASE_IMAGES=1", f"IMAGE_SUFFIX={SUFFIX}")
    built = _built(commands)
    written = _written(commands)

    # It writes no tag of a release image, the candidate's suffixed tags among
    # them, and builds the rest with no suffix: their bare tags are what the lanes'
    # Compose files run.
    assert written and not [tag for tag in written
                            if tag.removesuffix(SUFFIX).rsplit("-", 1)[0] in _release_tags()
                            or tag.removesuffix(SUFFIX) in _release_tags()]
    assert "arkhai:e2e-tests" in built and "arkhai:dev-env" in built
    assert not [tag for tag in written if tag.endswith(SUFFIX)]
    check = _index(commands, r"release_images\.py check ")
    down = _index(commands, r"docker compose .* down ")
    up = _index(commands, r"docker compose .* up -d --wait")
    record = _index(commands, r"release_images\.py record ")
    scenarios = _index(commands, r"^docker run --rm ")
    first_build = min(index for index, line in enumerate(commands) if "docker build" in line)
    assert check < down < first_build < up < record < scenarios
    # The check and the record read the same Compose files the lane brings up.
    up_words = shlex.split(commands[up])
    compose = up_words[up_words.index("compose") + 1:up_words.index("up")]
    for index in (check, record):
        assert shlex.split(_option(commands[index], "compose")) == compose
        assert _option(commands[index], "suffix") == SUFFIX
    assert f"--lane {lane} " in commands[record]


@pytest.mark.parametrize("lane", LANES)
def test_a_lane_run_without_the_switch_builds_its_release_images_and_records_nothing(
        lane: str) -> None:
    commands = lane_commands(lane)

    assert set(_built(commands)) & _release_tags()
    assert not [line for line in commands if "release_images.py" in line]


@pytest.mark.parametrize("lane", LANES)
def test_a_lane_refuses_a_release_images_value_other_than_one(lane: str) -> None:
    refused = subprocess.run(["make", "-n", f"test-e2e-{lane}", "RELEASE_IMAGES=yes"],
                             cwd=REPO_ROOT / "e2e-tests", capture_output=True, text=True,
                             env=_environment())

    assert refused.returncode != 0
    assert "RELEASE_IMAGES must be 1 or unset, not 'yes'" in refused.stderr


def test_pull_release_images_passes_the_registry_and_suffix() -> None:
    commands = _make_n(REPO_ROOT / "e2e-tests", "pull-release-images",
                       f"DOCKER_REGISTRY={REGISTRY}", f"IMAGE_SUFFIX={SUFFIX}")

    assert commands == [f'cd .. && python3 scripts/release_images.py pull --registry="{REGISTRY}" '
                        f'--suffix="{SUFFIX}"']


# --- the lanes' Compose files --------------------------------------------------


def _compose_arguments(lane: str) -> list[str]:
    commands = lane_commands(lane, "RELEASE_IMAGES=1", f"IMAGE_SUFFIX={SUFFIX}")
    return shlex.split(_option(commands[_index(commands, r"release_images\.py check ")],
                               "compose"))


def _images(lane: str, suffix: str | None) -> list[str]:
    if not shutil.which("docker") or subprocess.run(
            ["docker", "compose", "version"], capture_output=True).returncode != 0:
        if os.environ.get("COMPOSE_REQUIRED") == "1":
            pytest.fail("Docker Compose is required for deployment rendering")
        pytest.skip("Docker Compose is required for deployment rendering")
    env = {key: value for key, value in os.environ.items()
           if key not in ("PROVISIONING_MODE", "IMAGE_SUFFIX")}
    if suffix is not None:
        env["IMAGE_SUFFIX"] = suffix
    rendered = subprocess.run(["docker", "compose", *_compose_arguments(lane), "config",
                               "--images"], cwd=REPO_ROOT, capture_output=True, text=True,
                              env=env)
    assert rendered.returncode == 0, rendered.stderr
    return sorted(rendered.stdout.split())


@pytest.mark.parametrize("lane", LANES)
def test_a_lanes_compose_files_run_release_images_bare_unless_a_suffix_is_set(
        lane: str) -> None:
    bare = _images(lane, None)
    suffixed = _images(lane, SUFFIX)
    release = _release_tags()

    # Unset, the lane runs release images by the bare tags a build writes; set,
    # exactly those carry the suffix, none stays bare, and nothing else changes.
    assert release & set(bare)
    assert not release & set(suffixed)
    assert sorted(image + SUFFIX if image in release else image for image in bare) == suffixed


@pytest.mark.parametrize("lane", LANES)
def test_a_lane_on_release_images_builds_every_other_image_of_its_own_that_it_runs(
        lane: str) -> None:
    """The lane targets name which builds they drop; an image that leaves the
    declaration but is still dropped would be run and never built, whether its
    Compose line keeps the suffix or not."""
    written = _written(lane_commands(lane, "RELEASE_IMAGES=1", f"IMAGE_SUFFIX={SUFFIX}"))
    candidate = {f"{tag}{SUFFIX}" for tag in _release_tags()}
    own = {image for image in _images(lane, SUFFIX)
           if image.startswith("arkhai:") and image not in candidate}

    assert own and own <= written, f"run and not built: {sorted(own - written)}"
