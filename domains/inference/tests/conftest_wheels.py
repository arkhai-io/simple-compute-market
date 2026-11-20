from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[3]
INFERENCE = REPO / "domains" / "inference"


@pytest.fixture(scope="module")
def wheels(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    output = tmp_path_factory.mktemp("inference-wheels")
    projects = {
        "domain": (INFERENCE, "arkhai_inference_domain-*.whl"),
        "api": (REPO / "kit" / "api", "arkhai_api-*.whl"),
        "api-contracts": (REPO / "kit" / "api" / "contracts", "arkhai_api_contracts-*.whl"),
        "core": (REPO / "core", "arkhai_core-*.whl"),
        "identity": (REPO / "kit" / "identity", "arkhai_kit_identity-*.whl"),
        # The process time source, which the identity kit imports.
        "injected_time": (REPO / "tools" / "injected-time", "arkhai_injected_time-*.whl"),
    }
    built: dict[str, Path] = {}
    for name, (project, pattern) in projects.items():
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(output)],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        )
        matches = sorted(output.glob(pattern))
        assert len(matches) == 1
        built[name] = matches[0]
    return built


def _members(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def _metadata(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        return archive.read(metadata_name).decode()


_REQUIRES_DIST = re.compile(r"^Requires-Dist: ([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?([^;]*)$")


def _requirements(wheel: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in _metadata(wheel).splitlines():
        match = _REQUIRES_DIST.match(line)
        if match is None:
            continue
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        requirements[name] = match.group(2).strip()
    return requirements
