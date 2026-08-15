from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[3]
APICREDITS = REPO / "domains" / "apicredits"


def test_no_apicredits_project_declares_an_internal_editable_source() -> None:
    """Scoped to the API-credit domain only. The repository-wide version
    of this check -- covering every consumable project, not just this
    domain -- belongs to `remove-relative-uv-sources`, an existing,
    separate change already scoped to exactly that; this test does not
    duplicate it.
    """
    apicredits_pyprojects = sorted(APICREDITS.glob("**/pyproject.toml"))
    assert apicredits_pyprojects, "expected to find at least one pyproject.toml"

    violations: list[str] = []
    for path in apicredits_pyprojects:
        text = path.read_text()
        if "[tool.uv.sources]" in text:
            violations.append(str(path.relative_to(REPO)))

    assert violations == [], (
        f"internal editable [tool.uv.sources] override(s) found: {violations}"
    )


@pytest.fixture(scope="module")
def wheels(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    output = tmp_path_factory.mktemp("apicredits-wheels")
    projects = {
        "domain": (
            APICREDITS,
            "arkhai_apicredits_domain-*.whl",
        ),
        "buyer": (
            APICREDITS / "buyer",
            "arkhai_apicredits_buyer-*.whl",
        ),
        "storefront": (
            APICREDITS / "storefront",
            "arkhai_apicredits_storefront-*.whl",
        ),
        "vms_storefront": (
            REPO / "domains" / "vms" / "storefront",
            "arkhai_vms_storefront-*.whl",
        ),
        "bare_metal_storefront": (
            REPO / "domains" / "bare_metal" / "storefront",
            "arkhai_bare_metal_storefront-*.whl",
        ),
        "service": (
            APICREDITS / "service",
            "arkhai_apicredits_service-*.whl",
        ),
        "core": (REPO / "core", "arkhai_core-*.whl"),
        "core_storefront": (
            REPO / "core" / "storefront",
            "arkhai_core_storefront-*.whl",
        ),
        "core_registry_client": (
            REPO / "core" / "registry-client",
            "arkhai_core_registry_client-*.whl",
        ),
        "policy": (REPO / "kit" / "policy", "arkhai_kit_policy-*.whl"),
        "alkahest": (REPO / "kit" / "alkahest", "arkhai_kit_alkahest-*.whl"),
        "identity": (REPO / "kit" / "identity", "arkhai_kit_identity-*.whl"),
        "config": (REPO / "kit" / "config", "arkhai_kit_config-*.whl"),
        "site": (REPO / "kit" / "site", "arkhai_kit_site-*.whl"),
        "site_client": (REPO / "kit" / "site-client", "arkhai_kit_site_client-*.whl"),
        "settlement_runtime": (
            REPO / "kit" / "settlement-runtime",
            "arkhai_kit_settlement_runtime-*.whl",
        ),
        "negotiation_runtime": (
            REPO / "kit" / "negotiation-runtime",
            "arkhai_kit_negotiation_runtime-*.whl",
        ),
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


def test_domain_wheel_owns_shared_concepts(wheels: dict[str, Path]) -> None:
    members = _members(wheels["domain"])
    assert {
        "domains/apicredits/__init__.py",
        "domains/apicredits/domain_runtime.py",
        "domains/apicredits/schema.py",
        "domains/apicredits/listings/models.py",
        "domains/apicredits/negotiation/terms.py",
        "domains/apicredits/settlement/fulfillment.py",
    } <= members


def test_role_wheels_do_not_duplicate_shared_concepts(
    wheels: dict[str, Path],
) -> None:
    shared_files = {
        name
        for name in _members(wheels["domain"])
        if name.startswith("domains/apicredits/")
    }
    buyer_files = _members(wheels["buyer"])
    storefront_files = _members(wheels["storefront"])

    assert shared_files.isdisjoint(buyer_files)
    assert shared_files.isdisjoint(storefront_files)
    assert "domains/apicredits/buyer/cli.py" in buyer_files
    assert "apicredits_storefront/domain_runtime.py" in storefront_files


def test_role_wheels_require_shared_domain_and_versioned_core(
    wheels: dict[str, Path],
) -> None:
    domain_metadata = _metadata(wheels["domain"])
    buyer_metadata = _metadata(wheels["buyer"])
    storefront_metadata = _metadata(wheels["storefront"])

    assert "Requires-Dist: arkhai-core>=0.2.0" in domain_metadata
    assert "Requires-Dist: arkhai-apicredits-domain>=0.1.0" in buyer_metadata
    assert "Requires-Dist: arkhai-core>=0.2.0" in buyer_metadata
    assert "Requires-Dist: arkhai-core-buyer>=0.3.0" in buyer_metadata
    assert "Requires-Dist: arkhai-apicredits-domain>=0.1.0" in storefront_metadata
    assert "Requires-Dist: arkhai-core>=0.2.0" in storefront_metadata
    assert "Requires-Dist: arkhai-core-storefront>=0.3.0" in storefront_metadata


def test_storefront_wheels_require_settlement_runtime(
    wheels: dict[str, Path],
) -> None:
    for name in ("storefront", "vms_storefront", "bare_metal_storefront"):
        metadata = _metadata(wheels[name])
        assert "Requires-Dist: arkhai-kit-settlement-runtime>=0.1.0" in metadata, name


def test_migrated_storefront_wheels_require_negotiation_runtime(
    wheels: dict[str, Path],
) -> None:
    for name in ("storefront", "vms_storefront"):
        metadata = _metadata(wheels[name])
        assert (
            "Requires-Dist: arkhai-kit-negotiation-runtime==0.1.0" in metadata
        ), name


def test_storefront_wheel_exports_contract_constant(
    wheels: dict[str, Path],
) -> None:
    with zipfile.ZipFile(wheels["storefront"]) as archive:
        entry_points_name = next(
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_points_name).decode()

    assert "[market.storefront_domains]" in entry_points
    assert (
        "apicredits = apicredits_storefront.domain_runtime:APICREDITS_STOREFRONT_DOMAIN"
    ) in entry_points


def test_domain_contract_imports_from_built_wheel(
    wheels: dict[str, Path],
) -> None:
    venv = wheels["domain"].parent / "venv"
    subprocess.run(
        ["uv", "venv", str(venv)],
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
        ["uv", "venv", str(venv)],
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
        ["uv", "venv", str(venv)], check=True, capture_output=True, text=True
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
