"""Tests for the build and Helm targets a change's validation runs under its own names.

The build targets append `IMAGE_SUFFIX` to every image tag they write, and every
`helm/Makefile` target that takes `NAMESPACE=` also takes `CHANGE=`. Each is read
through `make -n`, which prints a target's commands without running them; the
helper scripts behind `forward`, `unforward`, `resume`, and `topology-secrets` run
for real against fake `kubectl`, `helm`, and `cast` executables on `PATH`, the
process boundary they wrap.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELM = REPO_ROOT / "helm"
SUFFIX = "-pilot"
NAMESPACE = "validate-pilot"
# A docker build's `-t <tag>` or a `docker tag <source> <tag>`.
_TAGS = re.compile(r"docker build .*?-t (\S+)|docker tag \S+ (\S+)")


def _environment(path: Path | None = None) -> dict[str, str]:
    # A make that ran these tests passes its command-line variables, CHANGE among
    # them, down through MAKEFLAGS; none of them may reach the targets read here.
    env = {key: value for key, value in os.environ.items()
           if key not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL", "CHANGE",
                          "IMAGE_SUFFIX", "NAMESPACE")}
    if path is not None:
        env["PATH"] = f"{path}:{env['PATH']}"
    return env


def _make_n(*arguments: str, directory: Path = REPO_ROOT) -> str:
    return subprocess.run(["make", "-n", "--no-print-directory", "-C", str(directory),
                           *arguments], capture_output=True, text=True, check=True,
                          env=_environment()).stdout


def _tags(commands: str) -> list[str]:
    joined = re.sub(r"\\\n\s*", " ", commands)
    return [build or tag for build, tag in _TAGS.findall(joined)]


# --- IMAGE_SUFFIX ---------------------------------------------------------------

ROOT_IMAGE_TARGETS = {
    "build-bare-metal-storefront": ["arkhai:bare-metal-storefront"],
    "build-apicredits-service": ["arkhai:apicredits-service"],
    "build-apicredits-storefront": ["arkhai:apicredits-storefront"],
    "build-apicredits-sample-app": ["arkhai:apicredits-sample-app"],
}
# Each subproject's image target, and the root target that delegates to it.
SUBPROJECT_IMAGE_TARGETS = {
    "core/registry": ("build-images", "build-registry", "arkhai:registry"),
    "domains/vms/storefront": ("build-images", "build-storefront", "arkhai:storefront"),
    "provisioning/compute/service": ("build-image", "build-provisioning",
                                     "arkhai:compute-provisioning"),
    "dev-env": ("build-images", "build-dev-env", "arkhai:dev-env"),
    "e2e-tests": ("build-images", "build-test-image", "arkhai:e2e-tests"),
}


@pytest.mark.parametrize("target", sorted(ROOT_IMAGE_TARGETS))
def test_a_root_image_target_appends_the_suffix(target: str) -> None:
    assert _tags(_make_n(target)) == ROOT_IMAGE_TARGETS[target]
    assert _tags(_make_n(target, f"IMAGE_SUFFIX={SUFFIX}")) == [
        tag + SUFFIX for tag in ROOT_IMAGE_TARGETS[target]]


@pytest.mark.parametrize("project", sorted(SUBPROJECT_IMAGE_TARGETS))
def test_a_subproject_image_target_appends_the_suffix_to_every_tag(project: str) -> None:
    target, _, image = SUBPROJECT_IMAGE_TARGETS[project]

    bare = _tags(_make_n(target, directory=REPO_ROOT / project))
    suffixed = _tags(_make_n(target, f"IMAGE_SUFFIX={SUFFIX}", directory=REPO_ROOT / project))

    # A bare build tags the image, then the same image with its commit; a
    # suffixed build tags it per change alone.
    assert len(bare) == 2 and bare[0] == image
    assert re.fullmatch(re.escape(image) + r"-[0-9a-f]+", bare[1])
    assert suffixed == [image + SUFFIX]


@pytest.mark.parametrize("project", sorted(SUBPROJECT_IMAGE_TARGETS))
def test_the_root_target_passes_the_suffix_to_its_subproject(project: str) -> None:
    _, root_target, _ = SUBPROJECT_IMAGE_TARGETS[project]

    assert f"cd {project} && make build IMAGE_SUFFIX={SUFFIX}" in _make_n(
        root_target, f"IMAGE_SUFFIX={SUFFIX}")
    assert f"cd {project} && make build IMAGE_SUFFIX=" in _make_n(root_target)


# The aggregate targets and the subprojects each delegates an image to.
AGGREGATE_TARGETS = {
    "build": ("core/registry", "domains/vms/storefront", "provisioning/compute/service"),
    "build-dev": tuple(SUBPROJECT_IMAGE_TARGETS),
    "build-seller": ("domains/vms/storefront", "provisioning/compute/service"),
}


@pytest.mark.parametrize("target", sorted(AGGREGATE_TARGETS))
def test_an_aggregate_target_suffixes_its_own_images_and_passes_the_suffix_down(
        target: str) -> None:
    # `make -n` prints the subprojects' `cd <project> && make build` without running
    # it, so the tags read here are the root targets' own; the subprojects' are
    # the tests above.
    bare = _make_n(target)
    suffixed = _make_n(target, f"IMAGE_SUFFIX={SUFFIX}")

    assert _tags(bare) and not any(tag.endswith(SUFFIX) for tag in _tags(bare))
    assert _tags(suffixed) == [tag + SUFFIX for tag in _tags(bare)]
    for project in AGGREGATE_TARGETS[target]:
        assert f"cd {project} && make build IMAGE_SUFFIX={SUFFIX}" in suffixed
        assert f"cd {project} && make build IMAGE_SUFFIX=\n" in bare + "\n"


def test_the_storefronts_uncached_build_appends_the_suffix() -> None:
    project = REPO_ROOT / "domains/vms/storefront"

    assert _tags(_make_n("build-no-cache", f"IMAGE_SUFFIX={SUFFIX}", directory=project)) == [
        "arkhai:storefront" + SUFFIX]


# --- CHANGE= in helm/Makefile ---------------------------------------------------

def _helm_setting(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["make", "-s", "--no-print-directory", "-C", str(HELM), "--eval",
                           "print-%: ; @echo $($*)", f"print-{name}", *arguments],
                          capture_output=True, text=True, env=_environment())


def test_change_derives_the_namespace_and_none_means_default() -> None:
    assert _helm_setting("NAMESPACE", "CHANGE=pilot").stdout == f"{NAMESPACE}\n"
    assert _helm_setting("NAMESPACE").stdout == "default\n"


def test_a_change_and_a_namespace_together_are_refused() -> None:
    refused = _helm_setting("NAMESPACE", "CHANGE=pilot", "NAMESPACE=other")

    assert refused.returncode != 0 and "not both" in refused.stderr


def test_a_change_with_no_namespace_is_refused() -> None:
    refused = _helm_setting("NAMESPACE", "CHANGE=Not_A_Change")

    assert refused.returncode != 0 and "names no validation namespace" in refused.stderr


@pytest.mark.parametrize("arguments", [
    ["template"], ["template-module", "MODULE=dev-env"], ["deploy"], ["deploy-local"],
    ["undeploy"], ["check-local-secrets"], ["test"], ["test-module", "MODULE=registry"],
    ["topology-up"], ["topology-down"], ["topology-check"], ["forward"], ["resume"],
])
def test_every_namespaced_target_takes_a_change(arguments: list[str]) -> None:
    commands = _make_n(*arguments, "CHANGE=pilot", directory=HELM)

    assert f"--namespace {NAMESPACE}" in commands or f'NAMESPACE="{NAMESPACE}"' in commands
    assert not re.search(r"""(--namespace |NAMESPACE=["']?)default\b""", commands)


def test_topology_secrets_runs_for_the_changes_namespace() -> None:
    commands = _make_n("topology-secrets", "CHANGE=pilot", directory=HELM)

    assert f'NAMESPACE="{NAMESPACE}"' in commands
    assert not re.search(r"""(--namespace |NAMESPACE=["']?)default\b""", commands)


# --- the scripts behind the targets ---------------------------------------------

def _executable(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body, "utf-8")
    path.chmod(0o755)


def _fake_kubectl(bin_dir: Path, log: Path, *, refuse_ports: Sequence[int] = (),
                  namespaces: str = "") -> None:
    refusals = "".join(
        f'case "$*" in *" {port}:{port}"*) '
        f'echo "Unable to listen on port {port}: bind: address already in use" >&2; '
        "exit 1;; esac\n" for port in refuse_ports)
    # A forward that listens takes a second to exit once signalled, as a real one
    # closing its connections may, so a stop that did not wait would find it alive.
    _executable(bin_dir, "kubectl", f"""echo "$*" >> {log}
{refusals}case "$1" in
  port-forward) echo $$ >> {log}.pids; echo "Forwarding from 127.0.0.1:$5"
    trap 'sleep 1; kill $!; exit 0' TERM; sleep 60 & wait;;
  get) case " {namespaces} " in *" $3 "*) exit 0;; esac; exit 1;;
  apply) cat > /dev/null; exit 0;;
  create) [ "$2" = secret ] && echo "kind: Secret"; exit 0;;
esac
exit 0
""")


def _make(*arguments: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["make", "--no-print-directory", "-C", str(HELM), *arguments],
                          capture_output=True, text=True, env=_environment(path))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _stop(pids: Sequence[int]) -> None:
    for pid in pids:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_forward_forwards_the_changes_namespace_and_unforward_waits_for_it(
        tmp_path: Path) -> None:
    log, pid_file = tmp_path / "kubectl.log", tmp_path / "forwards.pids"
    _fake_kubectl(tmp_path, log)

    started = _make("forward", "CHANGE=pilot", f"FORWARD_PID_FILE={pid_file}", path=tmp_path)
    pids = [int(pid) for pid in pid_file.read_text().split()]
    try:
        assert started.returncode == 0, started.stderr
        assert len(pids) == 4 and all(_alive(pid) for pid in pids)
        forwarded = log.read_text().splitlines()
        assert all(f"--namespace {NAMESPACE}" in line for line in forwarded)
        assert {line.split()[-1] for line in forwarded} == {
            "8545:8545", "8080:8080", "8001:8001", "8081:8081"}

        stopped = _make("unforward", f"FORWARD_PID_FILE={pid_file}", path=tmp_path)

        assert stopped.returncode == 0, stopped.stderr
        assert not pid_file.exists()
        assert not any(_alive(pid) for pid in pids)
    finally:
        _stop(pids)


def test_forwards_whose_ports_are_held_are_named_and_the_others_stopped(
        tmp_path: Path) -> None:
    log, pid_file = tmp_path / "kubectl.log", tmp_path / "forwards.pids"
    _fake_kubectl(tmp_path, log, refuse_ports=(8080, 8001))

    started = _make("forward", "CHANGE=pilot", f"FORWARD_PID_FILE={pid_file}", path=tmp_path)

    # The two forwards that listened, which the failure stops.
    listened = [int(pid) for pid in Path(f"{log}.pids").read_text().split()]
    try:
        assert started.returncode != 0
        for port in (8080, 8001):
            assert (f"port {port}: Unable to listen on port {port}: bind: address already "
                    "in use") in started.stderr
        assert not pid_file.exists()
        assert len(listened) == 2
        assert not any(_alive(pid) for pid in listened)
    finally:
        _stop(listened)


def test_unforward_fails_over_a_forward_that_outlives_it_and_keeps_its_process(
        tmp_path: Path) -> None:
    pid_file = tmp_path / "forwards.pids"
    stubborn = subprocess.Popen(["sh", "-c", "trap '' TERM; while :; do sleep 0.1; done"])
    pid_file.write_text(f"{stubborn.pid}\n", "utf-8")
    try:
        stopped = subprocess.run(
            ["make", "--no-print-directory", "-C", str(HELM), "unforward",
             f"FORWARD_PID_FILE={pid_file}"],
            capture_output=True, text=True, env={**_environment(), "WAIT_SECONDS": "1"})

        assert stopped.returncode != 0
        assert f"process(es) {stubborn.pid} still running 1s after being stopped" in (
            stopped.stderr)
        assert pid_file.read_text().split() == [str(stubborn.pid)]
    finally:
        stubborn.kill()
        stubborn.wait()


RELEASE_ONE = """\
---
# Source: arkhai-node-operator/charts/registry/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: arkhai-node-operator-registry
  labels:
    app.kubernetes.io/name: registry
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: registry
---
# Source: arkhai-node-operator/charts/storefront/templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: arkhai-node-operator-storefront-bob
spec:
  ports:
    - port: 8001
"""
RELEASE_TWO = """\
---
# Source: arkhai-node-operator/charts/example/templates/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: "arkhai-bare-metal-seller-example"
spec:
  replicas: 2
"""


def _fake_helm(bin_dir: Path, manifests: dict[str, str]) -> Path:
    log = bin_dir / "helm.log"
    for release, manifest in manifests.items():
        (bin_dir / f"{release}.yaml").write_text(manifest, "utf-8")
    _executable(bin_dir, "helm", f"""echo "$*" >> {log}
case "$1" in
  list) printf '%s\\n' {' '.join(manifests)};;
  get) cat {bin_dir}/"$3".yaml;;
esac
""")
    return log


def test_resume_restores_the_replica_counts_every_release_states(tmp_path: Path) -> None:
    log = tmp_path / "kubectl.log"
    _fake_kubectl(tmp_path, log)
    helm_log = _fake_helm(tmp_path, {"arkhai-node-operator": RELEASE_ONE,
                                     "arkhai-bare-metal-seller": RELEASE_TWO})

    resumed = _make("resume", "CHANGE=pilot", path=tmp_path)

    assert resumed.returncode == 0, resumed.stderr
    assert helm_log.read_text().splitlines() == [
        f"list --namespace {NAMESPACE} --short",
        f"get manifest arkhai-node-operator --namespace {NAMESPACE}",
        f"get manifest arkhai-bare-metal-seller --namespace {NAMESPACE}",
    ]
    assert log.read_text().splitlines() == [
        f"scale --namespace {NAMESPACE} deployment/arkhai-node-operator-registry --replicas=1",
        f"scale --namespace {NAMESPACE} statefulset/arkhai-bare-metal-seller-example --replicas=2",
    ]


def test_resume_of_named_releases_leaves_the_others(tmp_path: Path) -> None:
    log = tmp_path / "kubectl.log"
    _fake_kubectl(tmp_path, log)
    helm_log = _fake_helm(tmp_path, {"arkhai-node-operator": RELEASE_ONE,
                                     "arkhai-bare-metal-seller": RELEASE_TWO})

    resumed = _make("resume", "CHANGE=pilot", "RESUME_RELEASES=arkhai-node-operator",
                    path=tmp_path)

    assert resumed.returncode == 0, resumed.stderr
    assert helm_log.read_text().splitlines() == [
        f"get manifest arkhai-node-operator --namespace {NAMESPACE}"]
    assert log.read_text().splitlines() == [
        f"scale --namespace {NAMESPACE} deployment/arkhai-node-operator-registry --replicas=1"]


@pytest.mark.parametrize("manifests", [{}, {"arkhai-node-operator": "---\nkind: Service\n"}])
def test_resume_of_a_namespace_stating_no_workloads_fails(tmp_path: Path,
                                                          manifests: dict[str, str]) -> None:
    _fake_kubectl(tmp_path, tmp_path / "kubectl.log")
    _fake_helm(tmp_path, manifests)

    resumed = _make("resume", "CHANGE=pilot", path=tmp_path)

    assert resumed.returncode != 0 and "states Deployment or StatefulSet" in resumed.stderr
    assert not (tmp_path / "kubectl.log").exists()


@pytest.mark.parametrize("exists", [False, True])
def test_topology_secrets_creates_the_namespace_only_when_absent(tmp_path: Path,
                                                                 exists: bool) -> None:
    log = tmp_path / "kubectl.log"
    _fake_kubectl(tmp_path, log, namespaces=NAMESPACE if exists else "")
    # Development values only: cast answers every derivation with Anvil account 0's
    # published key and address, never for a public network.
    _executable(tmp_path, "cast", 'case "$2" in\n'
                "  private-key) echo 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;;\n"
                "  address) echo 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266;;\n"
                "esac\n")

    created = _make("topology-secrets", "CHANGE=pilot", path=tmp_path)

    assert created.returncode == 0, created.stderr
    calls = log.read_text().splitlines()
    assert calls[0] == f"get namespace {NAMESPACE}"
    namespace_created = [call for call in calls if call == f"create namespace {NAMESPACE}"]
    assert namespace_created == ([] if exists else [calls[1]])
    # Each Secret is rendered and applied in the namespace, and so is the deal
    # test's buyer-profile volume, created when absent.
    secrets = [call for call in calls if call.startswith("create secret")]
    applied = [call for call in calls if call.startswith("apply")]
    assert secrets and len(applied) == len(secrets) + 1
    assert all(f"--namespace {NAMESPACE}" in call for call in secrets + applied)
    assert f"get pvc arkhai-buyer-profiles --namespace {NAMESPACE}" in calls
