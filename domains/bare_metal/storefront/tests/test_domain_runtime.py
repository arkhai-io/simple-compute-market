from __future__ import annotations

from types import SimpleNamespace
import pytest
import arkhai_bare_metal_storefront.domain_runtime as domain_runtime
from arkhai_bare_metal.schema import BARE_METAL_SCHEMA_KIND, BareMetalMessage
from market_core import DomainCapability, validate_domain_contract
from core_storefront import (
    StorefrontDomainBinding,
    StorefrontSettlementBuildContext,
    build_domain_settlement_artifacts,
)
from market_identity import Ed25519Signer

from arkhai_bare_metal_storefront.domain_runtime import (
    BARE_METAL_STOREFRONT_DOMAIN,
    get_market_domain_contract,
)
from arkhai_bare_metal_storefront.runtime import (
    _portable_evidence_reference,
    _publish_portable_evidence_reference,
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

    assert contract.has_capability(DomainCapability.FULFILLMENT)
    assert contract.fulfillment is not None
    assert callable(contract.fulfillment.fulfill)
    assert not contract.has_capability(DomainCapability.COMPUTE_PROVISIONING)
    assert contract.capability(DomainCapability.COMPUTE_PROVISIONING) is None


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


def test_portable_evidence_reference_uses_accepted_resolver_and_uid() -> None:
    lifecycle = SimpleNamespace(
        accepted_binding=SimpleNamespace(
            option=SimpleNamespace(
                option=SimpleNamespace(
                    params={
                        "condition": {
                            "evaluator": {"resolver_id": "bare-metal-portable"}
                        }
                    }
                )
            )
        )
    )

    assert _portable_evidence_reference(
        lifecycle,
        "0x" + "ab" * 32,
    ) == (
        '{"kind":"portable-remote.v1","resolver_id":"bare-metal-portable",'
        '"uid":"0x' + "ab" * 32 + '"}'
    )


@pytest.mark.asyncio
async def test_portable_evidence_is_published_before_reference_is_encoded() -> None:
    lifecycle = SimpleNamespace(
        accepted_binding=SimpleNamespace(
            option=SimpleNamespace(
                option=SimpleNamespace(
                    params={
                        "condition": {
                            "evaluator": {"resolver_id": "bare-metal-portable"}
                        }
                    }
                )
            )
        )
    )
    evidence = SimpleNamespace(
        condition_anchor="0x" + "cd" * 32,
        canonical_json=lambda: '{"kind":"bare-metal.lease-ready-evidence.v1"}',
    )
    calls = []

    async def publish_fulfillment(**kwargs):
        calls.append(kwargs)
        return "0x" + "ef" * 32

    reference = await _publish_portable_evidence_reference(
        lifecycle,
        evidence,
        SimpleNamespace(publish_fulfillment=publish_fulfillment),
    )

    assert calls == [
        {
            "condition_anchor": "0x" + "cd" * 32,
            "evidence": '{"kind":"bare-metal.lease-ready-evidence.v1"}',
        }
    ]
    assert reference == (
        '{"kind":"portable-remote.v1","resolver_id":"bare-metal-portable",'
        '"uid":"0x' + "ef" * 32 + '"}'
    )


def test_portable_evidence_reference_requires_accepted_resolver() -> None:
    lifecycle = SimpleNamespace(
        accepted_binding=SimpleNamespace(
            option=SimpleNamespace(
                option=SimpleNamespace(params={"condition": {"evaluator": {}}})
            )
        )
    )

    try:
        _portable_evidence_reference(lifecycle, "sha256:" + "ab" * 32)
    except RuntimeError as exc:
        assert str(exc) == "hosted evidence resolver is unavailable"
    else:
        raise AssertionError("missing resolver was accepted")


def test_settlement_hook_consumes_common_context(monkeypatch) -> None:
    contract = get_market_domain_contract()
    buyer = Ed25519Signer(bytes.fromhex("11" * 32)).identity
    seller = Ed25519Signer(bytes.fromhex("22" * 32)).identity
    calls = []

    def build_plan(**kwargs):
        calls.append(kwargs)
        return {
            "settlement_plan": {
                "obligations": [{"mechanism": "alkahest.v1"}],
                "service_terms": {},
            },
            "accepted_escrow_terms": [],
        }

    monkeypatch.setattr(
        domain_runtime,
        "build_bare_metal_settlement_plan",
        build_plan,
    )
    context = StorefrontSettlementBuildContext(
        binding=StorefrontDomainBinding(
            offering_mode="bare_metal",
            domain_identity=contract.identity,
            contract_major=contract.contract_version.major,
            contract_minor=contract.contract_version.minor,
        ),
        negotiation_id="neg-a",
        listing_id="listing-a",
        site_id="site-a",
        proposal={"kind": "proposal"},
        agreed_amount=100,
        duration_seconds=3600,
        buyer_principal=buyer,
        seller_principal=seller,
        seller_wallet_address="0xseller",
        chain_config_paths={"base": "/config/base.json"},
    )

    artifacts = build_domain_settlement_artifacts(contract, context)

    assert artifacts.supplemental == {"accepted_escrow_terms": []}
    assert calls == [
        {
            "proposal": {"kind": "proposal"},
            "agreed_amount": 100,
            "duration_seconds": 3600,
            "buyer_principal": buyer,
            "seller_principal": seller,
            "seller_wallet_address": "0xseller",
            "chain_config_paths": context.chain_config_paths,
        }
    ]
