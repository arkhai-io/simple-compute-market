"""The provisioning image the build tags is the image `make push-images` publishes."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import publish_artifacts


def _make_dry_run(*arguments: str, cwd: Path = REPO_ROOT) -> str:
    result = subprocess.run(
        ["make", "--no-print-directory", "--dry-run", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _publisher_command(publish: str, target: str) -> list[str]:
    """The publisher invocation `push-images` makes for one image target."""
    commands = [shlex.split(line) for line in publish.splitlines()]
    [command] = [
        argv
        for argv in commands
        if argv[:2] == ["python3", "scripts/publish_artifacts.py"]
        and "image" in argv
        and argv[argv.index("--target") + 1] == target
    ]
    return command


def test_provisioning_build_produces_the_tag_consumed_by_push_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_suffix = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    build = _make_dry_run(
        "build",
        cwd=REPO_ROOT / "provisioning" / "compute" / "service",
    )
    publish = _make_dry_run(
        "push-images", "AR_PROJECT=test-project", "AR_LOCATION=us-central1"
    )

    local_image = f"arkhai:compute-provisioning-{git_suffix}"
    assert f"docker tag arkhai:compute-provisioning {local_image}" in build

    # The Makefile only names the publisher's arguments; the publisher derives
    # the tags, so run its own command-line parsing on the exact invocation
    # and record the docker commands it would issue.
    run = Mock()
    push_image = publish_artifacts.push_image
    monkeypatch.setattr(publish_artifacts, "push_image", lambda args: push_image(args, run))
    command = _publisher_command(publish, "provisioning")
    monkeypatch.setattr(sys, "argv", command[1:])
    publish_artifacts.main()

    remote_image = (
        "us-central1-docker.pkg.dev/test-project/test-project-docker/arkhai:provisioning"
    )
    assert [call.args[0] for call in run.call_args_list] == [
        ["docker", "tag", local_image, f"{remote_image}-{git_suffix}"],
        ["docker", "tag", local_image, remote_image],
        ["docker", "push", f"{remote_image}-{git_suffix}"],
        ["docker", "push", remote_image],
    ]
