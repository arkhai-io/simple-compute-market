"""An image must ship the storefront version its project declares.

Each storefront image installs its own distribution from the staged wheelhouse
by name and exact version, written into the Dockerfile. Nothing derives that
literal from the project it names, so a version bump that does not also edit the
Dockerfile leaves the image installing an older wheel that is still present in
`.dist`. The install succeeds, the image starts, and the route it serves is the
one from whichever version was written down -- a stale image that reports itself
healthy. This pins the two together so the drift is a failing test rather than a
wire-level refusal against a running stack.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every image that installs a repository storefront distribution by exact
#: version, paired with the project whose ``pyproject.toml`` declares it.
PINNED_STOREFRONTS = (
    ("arkhai-vms-storefront", "domains/vms/storefront"),
    ("arkhai-bare-metal-storefront", "domains/bare_metal/storefront"),
    ("arkhai-apicredits-storefront", "domains/apicredits/storefront"),
)

DOCKERFILES = (
    "domains/vms/storefront/Dockerfile",
    "domains/bare_metal/storefront/Dockerfile",
    "domains/apicredits/storefront/Dockerfile",
)


def _declared_version(project: str) -> str:
    text = (REPO_ROOT / project / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, f"{project}/pyproject.toml declares no version"
    return match.group(1)


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_every_storefront_pin_names_the_declared_version(dockerfile: str) -> None:
    text = (REPO_ROOT / dockerfile).read_text(encoding="utf-8")
    for distribution, project in PINNED_STOREFRONTS:
        declared = _declared_version(project)
        for pinned in re.findall(rf"{re.escape(distribution)}==([0-9][^\s\\]*)", text):
            assert pinned == declared, (
                f"{dockerfile} installs {distribution}=={pinned}, but "
                f"{project} declares {declared}; the image would ship the "
                f"older wheel from .dist"
            )


def test_the_guard_covers_every_pin_that_exists() -> None:
    """A new pinned storefront must arrive with its Dockerfile in the list."""

    named = {distribution for distribution, _ in PINNED_STOREFRONTS}
    found: set[tuple[str, str]] = set()
    for path in REPO_ROOT.glob("domains/*/*/Dockerfile"):
        text = path.read_text(encoding="utf-8")
        for distribution in re.findall(r"(arkhai-[a-z0-9-]*storefront)==", text):
            found.add((distribution, str(path.relative_to(REPO_ROOT))))
    unnamed = {item for item in found if item[0] not in named}
    assert not unnamed, f"storefront pins outside this guard: {sorted(unnamed)}"
    uncovered = {path for _, path in found} - set(DOCKERFILES)
    assert not uncovered, f"Dockerfiles with pins outside this guard: {sorted(uncovered)}"
