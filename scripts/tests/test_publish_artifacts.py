"""The developer push targets, from their Make recipes to the commands they run.

Each push target's recipe is read through `make -n` and its `publish_artifacts.py`
command line run with the subprocess stubbed at the script's own `run` seam, the
process boundary it wraps, so what is pushed is shown from the declaration the
script reads through to the `docker`, `helm` and `gcloud` commands it would run.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from publish_artifacts import main, push_image
from release_components import REPO_ROOT, Image, chart_field, load

DESTINATION = ("AR_PROJECT=example-project", "AR_LOCATION=example-region")
DOCKER_REGISTRY = "example-region-docker.pkg.dev/example-project/example-project-docker"
HELM_REGISTRY = "oci://example-region-docker.pkg.dev/example-project/example-project-helm"


def _environment() -> dict[str, str]:
    # A make running these tests passes its variables down through MAKEFLAGS.
    return {key: value for key, value in os.environ.items()
            if key not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL", "IMAGE_SUFFIX")}


def _arguments(target: str) -> list[str]:
    """The arguments `target`'s recipe passes publish_artifacts.py, read from
    `make -n`."""
    printed = subprocess.run(["make", "-n", "--no-print-directory", target, *DESTINATION],
                             cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                             env=_environment()).stdout
    for line in printed.splitlines():
        words = shlex.split(line)
        if "scripts/publish_artifacts.py" in words and "check" not in words:
            return words[words.index("scripts/publish_artifacts.py") + 1:]
    raise AssertionError(f"{target} runs no publish_artifacts.py command:\n{printed}")


def _revision() -> str:
    return subprocess.run(["git", "rev-parse", "--short=9", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()


def _commands(run: Mock) -> list[list[str]]:
    return [call.args[0] for call in run.call_args_list]


def _pushes(images: tuple[Image, ...], revision: str) -> list[list[str]]:
    expected = []
    for image in images:
        source = f"arkhai:{image.local}-{revision}"
        tags = [f"{DOCKER_REGISTRY}/arkhai:{image.name}-{revision}",
                f"{DOCKER_REGISTRY}/arkhai:{image.name}"]
        expected += [["docker", "tag", source, tag] for tag in tags]
        expected += [["docker", "push", tag] for tag in tags]
    return expected


def test_push_images_pushes_exactly_the_declared_images_under_both_tags() -> None:
    run = Mock()

    assert main(_arguments("push-images"), run=run) == 0

    assert _commands(run) == _pushes(load().images, _revision())


def test_push_images_pushes_provisioning_from_the_image_its_build_writes() -> None:
    run = Mock()

    main(_arguments("push-images"), run=run)

    revision = _revision()
    assert ["docker", "tag", f"arkhai:compute-provisioning-{revision}",
            f"{DOCKER_REGISTRY}/arkhai:provisioning-{revision}"] in _commands(run)


def test_push_dev_images_pushes_exactly_the_declared_development_images() -> None:
    run = Mock()

    assert main(_arguments("push-dev-images"), run=run) == 0

    assert _commands(run) == _pushes(load().development_images, _revision())


def test_push_charts_pushes_the_declared_charts_package() -> None:
    components = load()
    chart_yaml = (REPO_ROOT / components.chart.path / "Chart.yaml").read_text(encoding="utf-8")
    package = f"{chart_field(chart_yaml, 'name')}-{chart_field(chart_yaml, 'version')}.tgz"
    run = Mock()

    assert main(_arguments("push-charts"), run=run) == 0

    assert _commands(run) == [["helm", "push", str(REPO_ROOT / ".dist" / package),
                               HELM_REGISTRY]]


def test_push_cli_uploads_the_declared_binary_under_the_nine_character_revision() -> None:
    run = Mock()

    assert main(_arguments("push-cli"), run=run) == 0

    revision = _revision()
    assert len(revision) == 9
    assert _commands(run) == [
        ["gcloud", "artifacts", "generic", "upload", "--project=example-project",
         "--location=example-region", "--repository=example-project-cli",
         f"--package={binary.name}", f"--version={revision}",
         f"--source={REPO_ROOT / binary.path}"]
        for binary in load().binaries]


def test_a_failed_tag_stops_the_pushes() -> None:
    run = Mock(side_effect=subprocess.CalledProcessError(1, ["docker"]))

    with pytest.raises(subprocess.CalledProcessError):
        push_image("example.invalid", Image("provisioning", "compute-provisioning"), "abc", run)
    assert run.call_count == 1


def test_a_chart_with_no_version_is_reported(tmp_path: Path,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "release-components.json").write_text(
        (REPO_ROOT / "manifests" / "release-components.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    (tmp_path / "helm").mkdir()
    (tmp_path / "helm" / "Chart.yaml").write_text("name: arkhai-node-operator\n",
                                                  encoding="utf-8")
    run = Mock()

    assert main(["--project", "p", "--location", "l", "--prefix", "x", "chart",
                 "--registry", "r", "--dist-dir", str(tmp_path)], run=run, root=tmp_path) == 1

    assert "declares no name or no version" in capsys.readouterr().err
    run.assert_not_called()


def test_a_declaration_the_reader_refuses_is_reported(tmp_path: Path,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "release-components.json").write_text("{}", encoding="utf-8")
    run = Mock()

    assert main(["--project", "p", "--location", "l", "--prefix", "x", "images",
                 "--registry", "r", "--suffix", "abc"], run=run, root=tmp_path) == 1

    assert "required key 'images' is missing" in capsys.readouterr().err
    run.assert_not_called()


@pytest.mark.parametrize("missing", ["project", "location"])
def test_cli_requires_explicit_destination(missing: str) -> None:
    values = dict(project="example-project", location="example-region", prefix="example")
    values[missing] = ""
    command = [sys.executable, "scripts/publish_artifacts.py"]
    for key, value in values.items():
        command.extend([f"--{key}", value])
    completed = subprocess.run([*command, "check"], capture_output=True, text=True,
                               cwd=REPO_ROOT)
    assert completed.returncode == 2
    assert f"AR_{missing.upper()} is required" in completed.stderr
