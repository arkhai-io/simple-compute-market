"""Universal market-domain contract and external extension conformance."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    ContractVersion,
    DomainCapability,
    DomainCodecExample,
    DomainConformanceCase,
    DomainContractValidationError,
    DomainIdentity,
    ImmutableBuyerCapability,
    MarketDomainContract,
    assert_domain_conformance,
    validate_domain_contract,
    validate_domain_contracts,
)


class ExternalCodecs:
    """A fake domain implementation with no dependency on repository packages."""

    @staticmethod
    def _normalize(slot, value):
        if value.get("slot") != slot:
            raise ValueError(f"expected {slot}")
        return (slot, value["value"])

    def listing(self, value):
        return self._normalize("listing", value)

    def message(self, value):
        return self._normalize("message", value)

    def terms(self, value):
        return self._normalize("terms", value)

    def materialization(self, value):
        return self._normalize("materialization", value)

    def receipt(self, value):
        return self._normalize("receipt", value)

    def result(self, value):
        return self._normalize("result", value)


def _external_domain(identity: str = "external.example") -> MarketDomainContract:
    return MarketDomainContract(
        identity=DomainIdentity(identity),
        contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
        codecs=ExternalCodecs(),
        declared_capabilities=frozenset({DomainCapability.BUYER}),
        buyer=ImmutableBuyerCapability(
            register_commands=lambda app: None,
            build_provision_terms=lambda **payload: payload,
            select_policy=lambda: "external-policy",
            decode_result=lambda payload: payload["result"],
        ),
    )


def test_external_domain_passes_reusable_conformance_suite():
    domain = _external_domain()
    examples = {
        slot: DomainCodecExample(
            input={"slot": slot, "value": 7},
            expected=(slot, 7),
        )
        for slot in (
            "listing",
            "message",
            "terms",
            "materialization",
            "receipt",
            "result",
        )
    }
    assert_domain_conformance(
        DomainConformanceCase(
            contract=domain,
            capabilities=frozenset({DomainCapability.BUYER}),
            **examples,
        )
    )


def test_contract_is_immutable_and_identity_version_are_independent():
    domain = _external_domain()
    assert domain.identity == "external.example"
    assert domain.contract_version == ContractVersion(1, 0)
    with pytest.raises(FrozenInstanceError):
        domain.contract_version = ContractVersion(2, 0)


def test_unsupported_contract_version_names_domain_and_supported_range():
    domain = replace(_external_domain(), contract_version=ContractVersion(2, 0))
    with pytest.raises(
        DomainContractValidationError,
        match=r"external\.example.*unsupported.*2\.0.*1\.0",
    ):
        validate_domain_contract(domain)


def test_duplicate_identity_is_rejected_before_role_startup():
    with pytest.raises(DomainContractValidationError, match="duplicate.*same"):
        validate_domain_contracts((_external_domain("same"), _external_domain("same")))


def test_declared_capability_requires_complete_hook_set():
    class IncompleteBuyer:
        register_commands = lambda self, app: None

    domain = replace(_external_domain(), buyer=IncompleteBuyer())
    with pytest.raises(
        DomainContractValidationError,
        match="buyer.*missing callable hooks.*build_provision_terms",
    ):
        validate_domain_contract(domain)


def test_undeclared_capability_is_rejected():
    domain = replace(_external_domain(), declared_capabilities=frozenset())
    with pytest.raises(DomainContractValidationError, match="undeclared.*buyer"):
        validate_domain_contract(domain)


def test_domain_validation_errors_are_not_coerced():
    with pytest.raises(ValueError, match="expected listing"):
        _external_domain().codecs.listing({"slot": "message", "value": 1})
