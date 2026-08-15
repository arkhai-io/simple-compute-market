from dataclasses import dataclass

import pytest

from market_core import ContractVersion, DomainIdentity
from core_storefront.domain_plugins import (
    StorefrontContributionSelection,
    StorefrontDomainContribution,
    discover_storefront_domain_registry,
    parse_storefront_contribution_selections,
)
from core_storefront.domain_registry import StorefrontDomainRegistryError

from test_domain_registry import _contract


@dataclass(frozen=True)
class _EntryPoint:
    name: str
    value: str
    loaded: object

    def load(self):
        return self.loaded


def _selection(
    contribution_id: str,
    offering_mode: str,
    identity: str,
    version: ContractVersion = ContractVersion(1, 0),
):
    return StorefrontContributionSelection(
        contribution_id=contribution_id,
        offering_mode=offering_mode,
        domain_identity=DomainIdentity(identity),
        contract_version=version,
    )


def test_discovery_loads_each_configured_contribution_once_during_startup():
    calls = []
    vm_contract = _contract("compute.v1")
    bare_metal_contract = _contract("bare_metal.v1")

    def build_vm():
        calls.append("vms")
        return vm_contract

    def build_bare_metal():
        calls.append("bare_metal")
        return bare_metal_contract

    registry = discover_storefront_domain_registry(
        (
            _selection("vms", "vm", "compute.v1"),
            _selection("bare_metal", "bare_metal", "bare_metal.v1"),
        ),
        installed=(
            _EntryPoint(
                "bare_metal",
                "bm:contribution",
                StorefrontDomainContribution("bare_metal", build_bare_metal),
            ),
            _EntryPoint(
                "vms",
                "vm:contribution",
                StorefrontDomainContribution("vms", build_vm),
            ),
        ),
    )

    assert calls == ["vms", "bare_metal"]
    assert registry.resolve(registry.bindings[0]) is vm_contract
    assert registry.resolve(registry.bindings[1]) is bare_metal_contract


def test_discovery_rejects_absent_contribution_without_loading_another():
    calls = []

    def build_vm():
        calls.append("vms")
        return _contract("compute.v1")

    with pytest.raises(StorefrontDomainRegistryError, match="not installed"):
        discover_storefront_domain_registry(
            (_selection("bare_metal", "bare_metal", "bare_metal.v1"),),
            installed=(
                _EntryPoint(
                    "vms",
                    "vm:contribution",
                    StorefrontDomainContribution("vms", build_vm),
                ),
            ),
        )
    assert calls == []


def test_discovery_rejects_duplicate_entry_point_name_before_loading():
    contribution = StorefrontDomainContribution(
        "vms", lambda: _contract("compute.v1")
    )
    with pytest.raises(StorefrontDomainRegistryError, match="multiple"):
        discover_storefront_domain_registry(
            (_selection("vms", "vm", "compute.v1"),),
            installed=(
                _EntryPoint("vms", "one:contribution", contribution),
                _EntryPoint("vms", "two:contribution", contribution),
            ),
        )


@pytest.mark.parametrize(
    "loaded, message",
    [
        (object(), "must export StorefrontDomainContribution"),
        (
            StorefrontDomainContribution(
                "different", lambda: _contract("compute.v1")
            ),
            "mismatched id",
        ),
    ],
)
def test_discovery_rejects_invalid_contribution_object(loaded, message):
    with pytest.raises(StorefrontDomainRegistryError, match=message):
        discover_storefront_domain_registry(
            (_selection("vms", "vm", "compute.v1"),),
            installed=(_EntryPoint("vms", "vm:contribution", loaded),),
        )


@pytest.mark.parametrize(
    "selection, contract, message",
    [
        (
            _selection("vms", "vm", "compute.v1"),
            _contract("other.v1"),
            "configured compute.v1",
        ),
        (
            _selection("vms", "vm", "compute.v1", ContractVersion(1, 0)),
            _contract("compute.v1", version=ContractVersion(2, 0)),
            "configured 1.0",
        ),
    ],
)
def test_config_assertions_must_match_returned_contract(selection, contract, message):
    with pytest.raises(StorefrontDomainRegistryError, match=message):
        discover_storefront_domain_registry(
            (selection,),
            installed=(
                _EntryPoint(
                    "vms",
                    "vm:contribution",
                    StorefrontDomainContribution("vms", lambda: contract),
                ),
            ),
        )



def test_parse_explicit_public_contribution_config():
    parsed = parse_storefront_contribution_selections(
        [
            {
                "contribution": "vms",
                "offering_mode": "vm",
                "domain_identity": "compute.v1",
                "contract_version": "1.0",
            },
            {
                "contribution": "bare_metal",
                "offering_mode": "bare_metal",
                "domain_identity": "bare_metal.v1",
                "contract_version": "1.0",
            },
        ]
    )

    assert tuple(item.contribution_id for item in parsed) == ("vms", "bare_metal")
    assert parsed[0].contract_version == ContractVersion(1, 0)


@pytest.mark.parametrize(
    "configured",
    [
        [],
        [{"contribution": "vms"}],
        [
            {
                "contribution": "vms",
                "offering_mode": "vm",
                "domain_identity": "compute.v1",
                "contract_version": "1",
            }
        ],
        [
            {
                "contribution": "vms",
                "offering_mode": "vm",
                "domain_identity": "compute.v1",
                "contract_version": "1.0",
                "credential": "forbidden",
            }
        ],
    ],
)
def test_parse_config_rejects_missing_malformed_and_unknown_fields(configured):
    with pytest.raises(StorefrontDomainRegistryError):
        parse_storefront_contribution_selections(configured)