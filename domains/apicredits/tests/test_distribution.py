"""Structural assertions about the built wheels.

These read the wheel archives directly: what modules each one carries, what its
metadata requires, what it exports. No environment is created and nothing is
installed, so they run in about a second and need no interpreter beyond this
one, no network, and no build toolchain.

The installation behaviour these wheels must also satisfy is asserted in
test_distribution_install.py, which is slower and needs more of the machine.
The two were one file, and every failure it produced for a year was the
install half breaking for reasons unrelated to the structural half -- which
then did not run at all, because a collection error takes the file with it.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest

from conftest_wheels import APICREDITS, REPO, _members, _requirements, wheels

__all__ = ["wheels"]


def test_no_apicredits_project_declares_an_internal_editable_source() -> None:
    """Scoped to the API-credit domain only.

    Deliberately narrow: the repository-wide equivalent -- covering every
    consumable project rather than this domain -- is owned elsewhere, and
    duplicating it here would give two places an opinion about the same
    rule.
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
    """Each role wheel depends on the shared domain wheel and on its versioned
    core role package.

    This asserts the dependency edges and that each carries a version
    specifier, not what the specifier says. Which bound a consumer needs is
    decided where its dependency's contract changes, and a literal here would
    only restate the project's own pyproject, failing every time a bound is
    correctly moved.
    """
    expected = {
        "domain": {"arkhai-core"},
        "buyer": {"arkhai-apicredits-domain", "arkhai-core", "arkhai-core-buyer"},
        "storefront": {
            "arkhai-apicredits-domain",
            "arkhai-core",
            "arkhai-core-storefront",
        },
    }
    for role, names in expected.items():
        requirements = _requirements(wheels[role])
        missing = names - requirements.keys()
        assert not missing, f"{role} wheel does not require {sorted(missing)}"
        unbounded = sorted(name for name in names if not requirements[name])
        assert not unbounded, f"{role} wheel requires {unbounded} without a version"


def test_storefront_wheels_require_settlement_runtime(
    wheels: dict[str, Path],
) -> None:
    for name in ("storefront", "vms_storefront", "bare_metal_storefront"):
        assert "arkhai-kit-settlement-runtime" in _requirements(wheels[name]), name


def test_migrated_storefront_wheels_require_negotiation_runtime(
    wheels: dict[str, Path],
) -> None:
    for name in ("storefront", "vms_storefront"):
        assert "arkhai-kit-negotiation-runtime" in _requirements(wheels[name]), name


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


