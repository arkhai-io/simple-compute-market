from dataclasses import FrozenInstanceError

import pytest

from market_core import (
    ContractVersion,
    DomainCapability,
    DomainIdentity,
    ImmutableCodecCapability,
    ImmutableFulfillmentCapability,
    ImmutablePublicationCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MARKET_DOMAIN_CONTRACT_VERSION,
    MarketDomainContract,
)
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontDomainBindingError,
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
    StorefrontDomainRegistryError,
)


def _identity(value):
    return value


def _contract(
    identity: str,
    *,
    version: ContractVersion = MARKET_DOMAIN_CONTRACT_VERSION,
    missing: DomainCapability | None = None,
) -> MarketDomainContract:
    capabilities = {
        DomainCapability.STOREFRONT,
        DomainCapability.PUBLICATION,
        DomainCapability.SETTLEMENT,
        DomainCapability.FULFILLMENT,
    }
    if missing is not None:
        capabilities.remove(missing)
    return MarketDomainContract(
        identity=DomainIdentity(identity),
        contract_version=version,
        codecs=ImmutableCodecCapability(
            normalize_listing=_identity,
            normalize_message=_identity,
            normalize_terms=_identity,
            normalize_materialization=_identity,
            normalize_receipt=_identity,
            normalize_result=_identity,
        ),
        declared_capabilities=frozenset(capabilities),
        storefront=(
            None
            if missing is DomainCapability.STOREFRONT
            else ImmutableStorefrontCapability(run_negotiation_policy=_identity)
        ),
        publication=(
            None
            if missing is DomainCapability.PUBLICATION
            else ImmutablePublicationCapability(source_factory=_identity)
        ),
        settlement=(
            None
            if missing is DomainCapability.SETTLEMENT
            else ImmutableSettlementCapability(verify=_identity, build_plan=_identity)
        ),
        fulfillment=(
            None
            if missing is DomainCapability.FULFILLMENT
            else ImmutableFulfillmentCapability(fulfill=_identity)
        ),
    )


def _registration(mode: str, identity: str, contribution: str):
    return StorefrontDomainRegistration(
        offering_mode=mode,
        contract=_contract(identity),
        contribution_id=contribution,
    )


@pytest.mark.parametrize("reverse_registration_order", [False, True])
def test_two_exact_registrations_resolve_independently_of_registration_order(
    reverse_registration_order,
):
    vm = _registration("vm", "compute.v1", "vms")
    bare_metal = _registration("bare_metal", "bare_metal.v1", "bare_metal")
    supplied = (bare_metal, vm) if reverse_registration_order else (vm, bare_metal)

    registry = StorefrontDomainRegistry(supplied)

    assert registry.resolve_registration(vm.binding) is vm
    assert registry.resolve(vm.binding) is vm.contract
    assert registry.resolve_registration(bare_metal.binding) is bare_metal
    assert registry.resolve(bare_metal.binding) is bare_metal.contract
    assert registry.resolve_mode("vm") is vm
    assert registry.resolve_mode("bare_metal") is bare_metal
    with pytest.raises(StorefrontDomainBindingError, match="unknown.*offering mode"):
        registry.resolve_mode("missing")


def test_one_registration_is_still_explicit_and_has_no_default_lookup():
    vm = _registration("vm", "compute.v1", "vms")
    registry = StorefrontDomainRegistry((vm,))

    assert registry.bindings == (vm.binding,)
    with pytest.raises(StorefrontDomainBindingError, match="unknown"):
        registry.resolve(
            StorefrontDomainBinding(
                offering_mode="bare_metal",
                domain_identity=DomainIdentity("bare_metal.v1"),
                contract_major=1,
                contract_minor=0,
            )
        )


@pytest.mark.parametrize(
    "registrations, message",
    [
        (
            (
                _registration("vm", "compute.v1", "vms"),
                _registration("vm", "other.v1", "other"),
            ),
            "duplicate storefront offering mode",
        ),
        (
            (
                _registration("vm", "compute.v1", "vms"),
                _registration("bare_metal", "other.v1", "vms"),
            ),
            "duplicate storefront contribution id",
        ),
        (
            (
                _registration("vm", "compute.v1", "vms"),
                _registration("bare_metal", "compute.v1", "other"),
            ),
            "duplicate market domain identity",
        ),
    ],
)
def test_duplicate_registration_dimensions_fail(registrations, message):
    with pytest.raises(StorefrontDomainRegistryError, match=message):
        StorefrontDomainRegistry(registrations)


@pytest.mark.parametrize(
    "missing",
    [
        DomainCapability.STOREFRONT,
        DomainCapability.PUBLICATION,
        DomainCapability.SETTLEMENT,
        DomainCapability.FULFILLMENT,
    ],
)
def test_every_required_storefront_capability_is_validated(missing):
    incomplete = StorefrontDomainRegistration(
        offering_mode="vm",
        contract=_contract("compute.v1", missing=missing),
        contribution_id="vms",
    )

    with pytest.raises(StorefrontDomainRegistryError, match=missing.value):
        StorefrontDomainRegistry((incomplete,))


def test_unsupported_contract_version_fails_before_registry_is_available():
    unsupported = StorefrontDomainRegistration(
        offering_mode="vm",
        contract=_contract("compute.v1", version=ContractVersion(99, 0)),
        contribution_id="vms",
    )

    with pytest.raises(StorefrontDomainRegistryError, match="unsupported"):
        StorefrontDomainRegistry((unsupported,))


def test_strings_and_reconstructed_contracts_do_not_redirect_resolution():
    vm = _registration("vm", "compute.v1", "vms")
    registry = StorefrontDomainRegistry((vm,))

    with pytest.raises(StorefrontDomainBindingError, match="requires"):
        registry.resolve(vm.binding.as_record())
    with pytest.raises(StorefrontDomainBindingError, match="exact startup-owned"):
        registry.registration_for_contract("compute.v1")
    with pytest.raises(StorefrontDomainBindingError, match="does not match"):
        registry.resolve(
            StorefrontDomainBinding(
                offering_mode="bare_metal",
                domain_identity=vm.contract.identity,
                contract_major=vm.contract.contract_version.major,
                contract_minor=vm.contract.contract_version.minor,
            )
        )
    with pytest.raises(StorefrontDomainBindingError, match="unknown"):
        registry.resolve(
            StorefrontDomainBinding(
                offering_mode=vm.offering_mode,
                domain_identity=vm.contract.identity,
                contract_major=vm.contract.contract_version.major,
                contract_minor=vm.contract.contract_version.minor + 1,
            )
        )
    with pytest.raises(StorefrontDomainBindingError, match="exact startup-owned"):
        registry.registration_for_contract(_contract("compute.v1"))

    assert registry.resolve(vm.binding) is vm.contract
    assert registry.registration_for_contract(vm.contract) is vm


def test_projection_and_bindings_are_immutable_public_values():
    vm = _registration("vm", "compute.v1", "vms")
    registry = StorefrontDomainRegistry((vm,))

    with pytest.raises(FrozenInstanceError):
        registry.projection()[0].offering_mode = "bare_metal"
    with pytest.raises(FrozenInstanceError):
        vm.binding.offering_mode = "bare_metal"
    with pytest.raises(TypeError):
        registry.by_offering_mode["bare_metal"] = vm
