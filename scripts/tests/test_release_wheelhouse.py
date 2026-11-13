"""The wheelhouse the build makes holds every declared distribution's wheel, and
none of them requires the tool that freezes the release's binary.

CI builds the wheelhouse (`make dist-ci`) before this suite runs, so a declared
distribution that no build target makes, or that builds under another name or
version, fails here rather than when a release candidate is loaded.
"""

from __future__ import annotations

import email.parser
import re
import zipfile
from pathlib import Path

from release_components import REPO_ROOT, declared_wheels, load

DIST_DIR = REPO_ROOT / ".dist"


def test_every_declared_distribution_resolves_against_the_wheelhouse() -> None:
    missing = [wheel.name for wheel in declared_wheels(load(), REPO_ROOT, DIST_DIR)
               if not wheel.is_file()]

    assert not missing, (
        f"{DIST_DIR} holds no wheel for {len(missing)} declared distribution(s); "
        "build the wheelhouse with `make dist`: " + ", ".join(missing)
    )


def _requirements(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(name for name in archive.namelist()
                        if name.endswith(".dist-info/METADATA"))
        message = email.parser.BytesParser().parsebytes(archive.read(metadata))
    return message.get_all("Requires-Dist") or []


def test_no_declared_wheel_requires_the_tool_that_freezes_the_binary() -> None:
    # The release's `market` binary is frozen in its build image; a published
    # wheel requiring the freezing tool would make every install pull it in.
    requiring = [
        wheel.name for wheel in declared_wheels(load(), REPO_ROOT, DIST_DIR)
        if any(re.match(r"pyinstaller(?![A-Za-z0-9_.-])", requirement, re.IGNORECASE)
               for requirement in _requirements(wheel))
    ]

    assert not requiring, "these declared wheels require PyInstaller: " + ", ".join(requiring)
