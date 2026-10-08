from __future__ import annotations

import subprocess
from pathlib import Path


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
    publish = _make_dry_run("push-images", "AR_PROJECT=test-project")

    local_image = f"arkhai:compute-provisioning-{git_suffix}"
    remote_image = (
        "us-central1-docker.pkg.dev/test-project/test-project-docker/"
        f"arkhai:provisioning-{git_suffix}"
    )
    assert f"docker tag arkhai:compute-provisioning {local_image}" in build
    assert f"docker tag {local_image} {remote_image}" in publish
    assert f"docker push {remote_image}" in publish
