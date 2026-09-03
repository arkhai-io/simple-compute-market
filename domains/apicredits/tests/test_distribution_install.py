"""Installation behaviour of the built wheels.

Each of these creates a throwaway environment and installs wheels into it, to
assert what resolves when only the wheels are present -- the condition the
Docker runtime stages actually run under, where no source tree is on the path.
That cannot be checked in-process: this interpreter already has the source
importable, so an in-process import proves nothing about the wheel.

The cost is that these depend on an interpreter for which the whole dependency
set has wheels, and on being able to reach an index. Structural assertions that
need none of that live in test_distribution.py.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest_wheels import APICREDITS, REPO, _members, _metadata, wheels

__all__ = ["wheels"]


def test_domain_contract_imports_from_built_wheel(
    wheels: dict[str, Path],
) -> None:
    venv = wheels["domain"].parent / "venv"
    subprocess.run(
        # Pinned to the interpreter this suite is running under. `uv venv`
        # otherwise picks uv's own default, which differs by machine: where
        # that default is newer than the wheels available for it, the install
        # below falls back to building pydantic-core from source and fails for
        # a reason that has nothing to do with what is being tested. The
        # runtime stage this simulates uses the project's interpreter, so
        # matching it is also the more faithful simulation.
        ["uv", "venv", "--python", sys.executable, str(venv)],
        check=True,
        capture_output=True,
        text=True,
    )
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--find-links",
            str(wheels["domain"].parent),
            str(wheels["domain"]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    code = """
from pathlib import Path
from domains.apicredits import domain_runtime
contract = domain_runtime.market_domain()
module_path = Path(domain_runtime.__file__).resolve()
assert contract.identity == "api_credits.v1"
assert "site-packages" in module_path.parts
"""
    subprocess.run(
        [str(python), "-I", "-c", code],
        cwd=wheels["domain"].parent,
        check=True,
        capture_output=True,
        text=True,
    )


def test_service_schema_module_imports_from_built_wheel(
    wheels: dict[str, Path],
) -> None:
    """The service wheel installs controllers/db/middleware/models/services
    as flat top-level packages (no wrapping arkhai_apicredits_service
    package name, confirmed by inspecting the built wheel's own file
    list) -- this is the one package in this file that previously had no
    real-install-and-import coverage at all, unlike domain's existing
    test above.
    """
    venv = wheels["service"].parent / "venv-service"
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv)],
        check=True,
        capture_output=True,
        text=True,
    )
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--find-links",
            str(wheels["service"].parent),
            str(wheels["service"]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    code = """
from pathlib import Path
from db import models
module_path = Path(models.__file__).resolve()
assert hasattr(models, "ApiKey")
assert hasattr(models, "CreditGrant")
assert hasattr(models, "ConsumptionEvent")
assert "site-packages" in module_path.parts
"""
    subprocess.run(
        [str(python), "-I", "-c", code],
        cwd=wheels["service"].parent,
        check=True,
        capture_output=True,
        text=True,
    )


def test_storefront_domain_imports_resolve_without_a_raw_source_copy(
    wheels: dict[str, Path],
) -> None:
    """Simulates the storefront Docker runtime stage's actual condition:
    only the storefront's own src/ tree present (as ``COPY .../src ./src``
    puts there) plus the installed wheels -- deliberately no raw
    ``domains/`` source copy, unlike the Dockerfile's previous
    (now-removed) ``COPY domains/ ./domains/`` step. Every
    ``domains.apicredits.*`` module the storefront package's own code
    actually imports must resolve from the installed
    ``arkhai-apicredits-domain`` wheel with nothing else on the path to
    fall back to.
    """
    venv = wheels["storefront"].parent / "venv-storefront-runtime"
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv)],
        check=True,
        capture_output=True,
        text=True,
    )
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--find-links",
            str(wheels["storefront"].parent),
            str(wheels["domain"]),
            str(wheels["storefront"]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    runtime_root = wheels["storefront"].parent / "simulated-runtime"
    (runtime_root / "src").mkdir(parents=True)
    for item in (APICREDITS / "storefront" / "src").iterdir():
        dest = runtime_root / "src" / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    code = """
import importlib
for name in (
    "domains.apicredits.domain_runtime",
    "domains.apicredits.negotiation.storefront_round",
    "domains.apicredits.listings.models",
    "domains.apicredits.listings.pricing",
    "domains.apicredits.listings.reconciler",
    "domains.apicredits.negotiation.terms",
    "domains.apicredits.settlement",
):
    mod = importlib.import_module(name)
    assert "site-packages" in mod.__file__, (name, mod.__file__)
"""
    subprocess.run(
        [str(python), "-I", "-c", code],
        cwd=runtime_root,
        env={"PYTHONPATH": str(runtime_root / "src")},
        check=True,
        capture_output=True,
        text=True,
    )
