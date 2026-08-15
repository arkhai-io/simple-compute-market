from __future__ import annotations

from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainIdentity,
    ImmutableCodecCapability,
    ImmutableFulfillmentCapability,
    ImmutableSettlementCapability,
    MarketDomainContract,
)
from market_identity import Identity
import pytest

from core_storefront.domain_lifecycle import (
    StorefrontDomainLifecycleError,
    StorefrontFulfillmentContext,
    StorefrontFulfillmentPorts,
    StorefrontSettlementBuildContext,
    StorefrontSettlementFulfillmentInput,
    build_domain_settlement_artifacts,
    fulfill_domain,
)
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontThreadBinding,
)


def _identity(value):
    return value


def _contract(*, identity: str, build_plan, fulfill) -> MarketDomainContract:
    return MarketDomainContract(
        identity=DomainIdentity(identity),
        contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
        codecs=ImmutableCodecCapability(
            normalize_listing=_identity,
            normalize_message=_identity,
            normalize_terms=_identity,
            normalize_materialization=_identity,
            normalize_receipt=_identity,
            normalize_result=_identity,
        ),
        settlement=ImmutableSettlementCapability(
            verify=_identity,
            build_plan=build_plan,
        ),
        fulfillment=ImmutableFulfillmentCapability(fulfill=fulfill),
    )


def _binding(identity: str = "compute.v1") -> StorefrontDomainBinding:
    return StorefrontDomainBinding(
        offering_mode="vm" if identity == "compute.v1" else "bare_metal",
        domain_identity=DomainIdentity(identity),
        contract_major=1,
        contract_minor=0,
    )


def _principal(value: str) -> Identity:
    return Identity(scheme="ed25519", identifier=value)


def _settlement_context(identity: str = "compute.v1") -> StorefrontSettlementBuildContext:
    return StorefrontSettlementBuildContext(
        binding=_binding(identity),
        negotiation_id="neg-1",
        listing_id="listing-1",
        site_id="site-a",
        proposal={"kind": "proposal"},
        agreed_amount=5000,
        duration_seconds=3600,
        buyer_principal=_principal("buyer"),
        seller_principal=_principal("seller"),
    )


def _fulfillment_context(identity: str = "bare_metal.v1") -> StorefrontFulfillmentContext:
    return StorefrontFulfillmentContext(
        thread_binding=StorefrontThreadBinding(
            negotiation_id="neg-1",
            listing_id="listing-1",
            site_id="site-a",
            binding=_binding(identity),
        ),
        escrow_uid="escrow-1",
        buyer_principal=_principal("buyer"),
        ports=StorefrontFulfillmentPorts(
            repository=object(),
            capacity_client=object(),
            fulfillment_client=object(),
        ),
    )


def test_prepared_fulfillment_input_freezes_domain_payload_and_redacts_ports():
    raw = {"listing_id": "listing-1"}
    evidence_client = object()
    prepared = StorefrontSettlementFulfillmentInput(
        thread_binding=_fulfillment_context().thread_binding,
        buyer_principal=_principal("buyer"),
        domain_input=raw,
        fulfillment_anchor="condition-1",
        evidence_client=evidence_client,
    )
    raw["listing_id"] = "changed"

    assert prepared.domain_input == {"listing_id": "listing-1"}
    assert prepared.site_id == "site-a"
    assert prepared.evidence_client is evidence_client
    assert "evidence_client" not in repr(prepared)


def test_settlement_builder_receives_one_exact_immutable_context():
    received = []

    def build_plan(*, context):
        received.append(context)
        return {
            "settlement_plan": {
                "obligations": [{"payer": "buyer", "claimant": "seller"}]
            },
            "accepted_terms": {"safe": True},
        }

    async def fulfill(*, context):
        raise AssertionError("not called")

    domain = _contract(identity="compute.v1", build_plan=build_plan, fulfill=fulfill)
    context = _settlement_context()

    artifacts = build_domain_settlement_artifacts(domain, context)

    assert received == [context]
    assert artifacts.settlement_plan["obligations"][0]["payer"] == "buyer"
    assert artifacts.supplemental == {"accepted_terms": {"safe": True}}


def test_cross_domain_settlement_swap_fails_before_hook():
    called = False

    def build_plan(*, context):
        nonlocal called
        called = True
        return {"settlement_plan": {"obligations": [{}]}}

    async def fulfill(*, context):
        raise AssertionError("not called")

    domain = _contract(identity="bare_metal.v1", build_plan=build_plan, fulfill=fulfill)

    with pytest.raises(StorefrontDomainLifecycleError, match="disagrees"):
        build_domain_settlement_artifacts(domain, _settlement_context())
    assert called is False


@pytest.mark.asyncio
async def test_fulfillment_result_must_retain_operation_and_site_binding():
    async def fulfill(*, context):
        return {
            "negotiation_id": context.negotiation_id,
            "escrow_uid": context.escrow_uid,
            "site_id": context.site_id,
            "physical_resource_id": "host-7",
            "state": "active",
            "capacity_reservation_id": "reservation-7",
            "fulfillment_id": "fulfillment-7",
        }

    domain = _contract(
        identity="bare_metal.v1",
        build_plan=lambda **_: {"settlement_plan": {"obligations": [{}]}},
        fulfill=fulfill,
    )
    context = _fulfillment_context()

    result = await fulfill_domain(domain, context)

    assert result.site_id == "site-a"
    assert result.physical_resource_id == "host-7"
    assert result.fulfillment_id == "fulfillment-7"


@pytest.mark.asyncio
async def test_fulfillment_result_cannot_retarget_another_site():
    async def fulfill(*, context):
        return {
            "negotiation_id": context.negotiation_id,
            "escrow_uid": context.escrow_uid,
            "site_id": "site-b",
            "physical_resource_id": "host-7",
            "state": "active",
        }

    domain = _contract(
        identity="bare_metal.v1",
        build_plan=lambda **_: {"settlement_plan": {"obligations": [{}]}},
        fulfill=fulfill,
    )

    with pytest.raises(StorefrontDomainLifecycleError, match="changed"):
        await fulfill_domain(domain, _fulfillment_context())
