from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path
from unittest.mock import Mock

from publish_artifacts import push_image


REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_dry_run(*arguments: str, cwd: Path = REPO_ROOT) -> str:
    result = subprocess.run(
        ["make", "--no-print-directory", "--dry-run", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _image_arguments(publish: str, target: str) -> argparse.Namespace:
    """The `image` arguments push-images passes publish_artifacts.py for one target."""
    for line in publish.splitlines():
        words = shlex.split(line)
        if "image" not in words:
            continue
        options = words[words.index("image") + 1:]
        values = dict(zip(options[::2], options[1::2]))
        if values.get("--target") == target:
            return argparse.Namespace(
                **{name.removeprefix("--"): value for name, value in values.items()}
            )
    raise AssertionError(f"push-images publishes no image for target {target}:\n{publish}")


def test_provisioning_build_produces_the_tag_consumed_by_push_images() -> None:
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
        "push-images", "AR_PROJECT=test-project", "AR_LOCATION=test-region"
    )

    local_image = f"arkhai:compute-provisioning-{git_suffix}"
    assert f"docker tag arkhai:compute-provisioning {local_image}" in build

    # The arguments push-images passes, read from its own command line, must make
    # publish_artifacts.py tag and push from the image the build wrote.
    arguments = _image_arguments(publish, "provisioning")
    run = Mock()
    push_image(arguments, run)
    remote_image = (
        "test-region-docker.pkg.dev/test-project/test-project-docker/"
        f"arkhai:provisioning-{git_suffix}"
    )
    commands = [call.args[0] for call in run.call_args_list]
    assert ["docker", "tag", local_image, remote_image] in commands
    assert ["docker", "push", remote_image] in commands
