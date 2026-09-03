from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[3]
APICREDITS = REPO / "domains" / "apicredits"


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
        "capacity_publication": (
            REPO / "kit" / "capacity-publication",
            "arkhai_kit_capacity_publication-*.whl",
        ),
        "storefront_kit": (
            REPO / "kit" / "storefront",
            "arkhai_kit_storefront-*.whl",
        ),
        "config": (REPO / "kit" / "config", "arkhai_kit_config-*.whl"),
        "site": (REPO / "kit" / "site", "arkhai_kit_site-*.whl"),
        "site_client": (REPO / "kit" / "site-client", "arkhai_kit_site_client-*.whl"),
        "settlement_runtime": (
            REPO / "kit" / "settlement-runtime",
            "arkhai_kit_settlement_runtime-*.whl",
        ),
        "hosted_settlement": (
            REPO / "kit" / "hosted-settlement",
            "arkhai_kit_hosted_settlement-*.whl",
        ),
        "resource_pools": (
            REPO / "kit" / "resource-pools",
            "arkhai_kit_resource_pools-*.whl",
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
    # Separately released dependencies stay out of this repository-owned wheel set.
    # Installation tests resolve them from the package index, like runtime installs do.
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


