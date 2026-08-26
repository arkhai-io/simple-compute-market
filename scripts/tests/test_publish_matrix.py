"""What the publish workflow builds follows from what each package declares."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish-pypi.yml"


def _packages() -> list[dict[str, object]]:
    """The PACKAGES table the workflow heredocs into `packages.json`."""

    text = WORKFLOW.read_text(encoding="utf-8")
    body = re.search(r"cat > packages\.json <<'JSON'\n(.*?)\n\s*JSON\n", text, re.S)
    assert body, "publish-pypi.yml no longer states its package table as a heredoc"
    return json.loads(re.sub(r"^ {10}", "", body.group(1), flags=re.M))


def _escaping_force_includes(package: Path) -> list[str]:
    """Wheel contents this package pulls from outside its own directory.

    A `../` source is the thing an sdist tarball cannot carry: the tarball is
    rooted at the package, so `uv build`'s default sdist->wheel rebuild finds
    nothing at that path and fails.
    """

    declared = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    forced = (
        declared.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("force-include", {})
    )
    return sorted(source for source in forced if source.startswith("../"))


@pytest.mark.parametrize("package", _packages(), ids=lambda entry: str(entry["key"]))
def test_a_package_reaching_outside_itself_publishes_a_wheel_only(
    package: dict[str, object],
) -> None:
    """The two facts have to agree, and only one of them was maintained.

    The workflow's own comment says why the buyer plugins are wheel-only, and
    names them as if that set were closed. `vms-storefront` acquired the same
    `../` force-includes and nothing noticed, so every publish of it since has
    died inside `hatchling.build.build_wheel` with `Forced include not found`
    pointing at a path in uv's sdist cache -- a message that names neither the
    package nor the reason.
    """

    directory = REPO_ROOT / str(package["path"])
    if not (directory / "pyproject.toml").is_file():
        pytest.skip(f"{package['path']} is not checked out here")

    escaping = _escaping_force_includes(directory)
    if not escaping:
        return

    assert package.get("wheel_only") is True, (
        f"{package['dist']} force-includes {escaping} from outside {package['path']}, "
        "which an sdist cannot carry; publish it as a wheel only"
    )
