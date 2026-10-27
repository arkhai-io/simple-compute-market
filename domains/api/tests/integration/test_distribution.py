"""The built wheel installs and imports with no core, storefront, or runtime package present."""

import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
_REQUIRES_DIST = re.compile(r"^Requires-Dist: ([A-Za-z0-9][A-Za-z0-9._-]*)")


@pytest.fixture(scope="module")
def wheels(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    output = tmp_path_factory.mktemp("api-wheels")
    built: dict[str, Path] = {}
    for name, project, pattern in (
        ("api", REPO / "domains" / "api", "arkhai_api-*.whl"),
        ("identity", REPO / "kit" / "identity", "arkhai_kit_identity-*.whl"),
    ):
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(output)],
            cwd=project, check=True, capture_output=True, text=True,
        )
        (built[name],) = sorted(output.glob(pattern))
    return built


def _members(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def _requirements(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        text = archive.read(metadata).decode()
    return {m.group(1).lower() for m in map(_REQUIRES_DIST.match, text.splitlines()) if m}


def test_the_wheel_carries_the_vocabulary_and_requires_only_foundation_kits(wheels):
    assert {
        "arkhai_api/__init__.py",
        "arkhai_api/labels.py",
        "arkhai_api/purchase.py",
        "arkhai_api/issuance.py",
        "arkhai_api/evidence.py",
        "arkhai_api/py.typed",
    } <= _members(wheels["api"])
    assert _requirements(wheels["api"]) == {"arkhai-kit-identity", "pydantic"}


def test_the_wheel_imports_with_no_core_storefront_or_runtime_package(wheels):
    venv = wheels["api"].parent / "venv"
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv)], check=True, capture_output=True, text=True
    )
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), "--find-links", str(wheels["api"].parent), str(wheels["api"])],
        check=True, capture_output=True, text=True,
    )
    code = """
import importlib, importlib.util
for name in ("arkhai_api.labels", "arkhai_api.purchase", "arkhai_api.issuance", "arkhai_api.evidence"):
    assert "site-packages" in importlib.import_module(name).__file__, name
for absent in ("market_core", "market_storefront", "apicredits_storefront", "arkhai_apicredits",
               "market_settlement_runtime", "market_negotiation_runtime", "market_site"):
    assert importlib.util.find_spec(absent) is None, absent
"""
    subprocess.run([str(python), "-I", "-c", code], cwd=venv.parent, check=True, capture_output=True, text=True)
