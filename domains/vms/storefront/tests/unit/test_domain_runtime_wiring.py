from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from core_storefront.models.listing_models import CreateListingRequest
from market_core import (
    ContractVersion,
    DomainCapability,
    DomainContractValidationError,
    DomainIdentity,
)

import market_storefront.server as server
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    validate_vm_storefront_domain,
)
from market_storefront.services.listing_service import ListingService
from tests.fake_site import TEST_MARKETPLACE_SIGNER

_ACCEPTED_ESCROWS = [
    {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "literal_fields": {
            "token": "0x0000000000000000000000000000000000000001"
        },
        "rates": [{"field": "amount", "per": "hour", "value": "5000"}],
    }
]


def _incompatible_domains() -> list[tuple[str, object, str]]:
    valid = build_vm_storefront_domain()
    return [
        ("wrong type", object(), "MarketDomainContract"),
        (
            "wrong identity",
            replace(valid, identity=DomainIdentity("bare_metal.v1")),
            "requires domain compute.v1",
        ),
        (
            "unsupported version",
            replace(valid, contract_version=ContractVersion(99, 0)),
            "unsupported market contract version",
        ),
        (
            "missing declaration",
            replace(
                valid,
                declared_capabilities=valid.declared_capabilities
                - {DomainCapability.SETTLEMENT},
                settlement=None,
            ),
            "missing required VM storefront capabilities: settlement",
        ),
        (
            "undeclared implementation",
            replace(
                valid,
                declared_capabilities=valid.declared_capabilities
                - {DomainCapability.SETTLEMENT},
            ),
            "provides undeclared capability 'settlement'",
        ),
        (
            "incomplete codecs",
            replace(valid, codecs=SimpleNamespace(listing=lambda value: value)),
            "incomplete codec capability",
        ),
        (
            "incomplete hook",
            replace(
                valid,
                settlement=SimpleNamespace(
                    verify=lambda **_kwargs: None,
                    build_plan=None,
                ),
            ),
            "capability 'settlement' is incomplete",
        ),
    ]


def test_vm_storefront_contract_is_validated_without_replacement() -> None:
    domain = build_vm_storefront_domain()

    assert validate_vm_storefront_domain(domain) is domain
    assert domain.identity == "compute.v1"
    assert domain.codecs.listing(
        {"gpu_model": "H200", "gpu_count": 1}
    ).offer_resource == {
        "gpu_model": "H200",
        "gpu_count": 1,
    }


@pytest.mark.parametrize(
    ("_case", "domain", "message"),
    _incompatible_domains(),
)
def test_incompatible_domain_fails_before_app_collaborators(
    monkeypatch,
    _case: str,
    domain: object,
    message: str,
) -> None:
    lifespan_builder = Mock()
    app_builder = Mock()
    monkeypatch.setattr(server, "build_vm_storefront_lifespan", lifespan_builder)
    monkeypatch.setattr(server, "build_storefront_app", app_builder)

    with pytest.raises(DomainContractValidationError, match=message):
        server.build_vm_storefront_app(domain=domain)

    lifespan_builder.assert_not_called()
    app_builder.assert_not_called()


def test_listing_service_validates_offer_through_injected_domain() -> None:
    domain = build_vm_storefront_domain()
    service = ListingService(
        domain=domain,
        sqlite_client=SimpleNamespace(market_domain=domain),
        alkahest_clients=None,
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
    )

    with pytest.raises(ValueError, match="offer_resource must include gpu_model"):
        service._parse_offer_and_escrows(
            CreateListingRequest(
                offer={"gpu_count": 1},
                accepted_escrows=_ACCEPTED_ESCROWS,
            )
        )
