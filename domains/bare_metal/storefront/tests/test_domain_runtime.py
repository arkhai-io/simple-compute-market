from __future__ import annotations

from arkhai_bare_metal.schema import BARE_METAL_SCHEMA_KIND, BareMetalMessage
from market_core import DomainCapability, validate_domain_contract

from arkhai_bare_metal_storefront.domain_runtime import (
    BARE_METAL_STOREFRONT_DOMAIN,
    get_market_domain_contract,
)


def test_storefront_contract_validates_current_bare_metal_capabilities() -> None:
    contract = get_market_domain_contract()

    assert contract is BARE_METAL_STOREFRONT_DOMAIN
    assert validate_domain_contract(contract) is contract
    assert str(contract.identity) == BARE_METAL_SCHEMA_KIND
    assert contract.has_capability(DomainCapability.PUBLICATION)
    assert contract.publication is not None
    assert callable(contract.publication.source_factory)
    assert contract.has_capability(DomainCapability.STOREFRONT)
    assert contract.storefront is not None
    assert callable(contract.storefront.run_negotiation_policy)
    assert contract.has_capability(DomainCapability.SETTLEMENT)
    assert contract.settlement is not None
    assert callable(contract.settlement.verify)
    assert callable(contract.settlement.build_plan)

    for capability in (
        DomainCapability.FULFILLMENT,
        DomainCapability.COMPUTE_PROVISIONING,
    ):
        assert not contract.has_capability(capability)
        assert contract.capability(capability) is None


def test_storefront_contract_retains_bare_metal_codecs() -> None:
    message = get_market_domain_contract().codecs.message(
        {
            "kind": BARE_METAL_SCHEMA_KIND,
            "duration_seconds": 3600,
            "access_method": "ssh",
            "ssh_public_key": "ssh-ed25519 buyer",
        },
    )

    assert isinstance(message, BareMetalMessage)
    assert message.duration_seconds == 3600
