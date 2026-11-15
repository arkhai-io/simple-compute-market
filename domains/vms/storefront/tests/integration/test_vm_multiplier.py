"""VM multiplier arithmetic and durable shape-independent concession behavior."""
from __future__ import annotations

import json
import math
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import AsyncMock

from compute_delivery import agreement_window
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction

import pytest

from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.negotiation_amounts import amount_codec
from arkhai_vms_negotiation.storefront_round import SellerRoundResult
from market_core.schemas import ProvisionTerms, derive_settlement_option_id
from market_negotiation_runtime import OfferUnfulfillableError
from core_storefront.aggregation import fill_first
from market_capacity_publication import CapacityRuntime, CapacitySite, PublicationBinding
from market_resource_pools_contracts.backing import BACKED
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
)
from market_policy.scalar_policies import bisection_middleware
from market_storefront.negotiation_runtime import build_vm_negotiation_runtime
from market_storefront.services.vm_job_spec_service import compute_capacity_claim_from_order
from market_storefront.services.vm_fulfillment_planner import build_vm_fulfillment_plan
from market_storefront.delivery_ports import VmDeliveryDomain
from market_storefront.delivery_records import register_delivery
from market_storefront.settlement_stages import delivery_facts, vm_evidence
from tests.integration.test_capacity_reservation_boundary import SITE_AUTHORITIES, site_app, _client
from tests._settings_overrides import settings_overrides
from tests.fake_site import FakeProjectionSite, loaded_site_projection_state
from tests.unit.test_sync_negotiation_seller_round_hook import db, marketplace_dependencies
from tests.unit import test_sync_negotiation_seller_round_hook as fixture


async def prepare(db, hourly=100, capacity_runtime=None, seller_round_hook=None):
    record = await db.load_listing(listing_id="L-hook")
    resource = {**json.loads(record["listing_resource"]), "vcpu_count": 4}
    option = fixture._option().model_dump(mode="json")
    option["price"]["rates"][0]["value"] = str(hourly)
    option["settlement"]["accepted_escrow"]["rates"][0]["value"] = str(hourly)
    option.pop("option_id")
    option["option_id"] = derive_settlement_option_id(**option)
    await db.update_listing(
        listing_id="L-hook", listing_resource=resource,
        settlement_options=[option],
    )
    await fixture._reprice(db, fixture._structure({"gpu": "60", "cpu": "10"}))
    state = await loaded_site_projection_state({"site-test": FakeProjectionSite(resource_pools=[{
        "pool_id": "pool-L-hook", "pool_metadata": {"policy_tags": {"listing_shapes": {"vm": [{
            "gpu": {"model": "H200", "count": 1}, "cpu": {"count": {"offer": 4, "max": 8}},
        }]}}},
    }])})
    registration = db.domain_registry.resolve_mode("vm")
    def runtime():
        return build_vm_negotiation_runtime(
            registration.contract, registry=db.domain_registry, binding=registration.binding,
            capacity_runtime=capacity_runtime or fixture._capacity_runtime(), site_projections=state,
            seller_round_hook=seller_round_hook,
            listing_source_check=fixture._source_matches,
        )
    def proposal(amount):
        return {"fields": {"amount": amount}, "settlement_selection": {
            "option_id": option["option_id"], "settlement": {"schema": "alkahest.v1"},
            "expiration_unix": 1_900_000_000,
        }}
    return await db.load_listing(listing_id="L-hook"), runtime, proposal


async def test_shape_change_keeps_the_floor_and_exact_payment_through_persistence(db):
    hourly = 10**30 + 7
    listing, runtime, proposal = await prepare(db, hourly=hourly)
    opened = await runtime().start(
        repository=db, listing_id="L-hook", buyer_principal=fixture._BUYER,
        seller_principal=fixture._SELLER, actor_principal=fixture._BUYER,
        proposal=proposal(9000), terms=ProvisionTerms(kind="compute.v1", version=1, payload={
            "duration_seconds": 1801, "ssh_public_key": "ssh-ed25519 public-development-fixture",
            "compute_resource": {"gpu_model": "H200", "gpu_count": 1, "vcpu_count": 4},
        }), seller_agent_url="http://seller.test", buyer_agent_url="http://buyer.test",
    )
    assert opened["proposal"]["fields"]["amount"] == "10000"
    revised = proposal(9500)
    revised["provision_terms"] = {"kind": "compute.v1", "version": 1, "payload": {
        "gpu": {"model": "H200", "count": 1}, "cpu": {"count": 3},
    }}
    async def continue_(action, value):
        return await runtime().continue_negotiation(
            repository=db, negotiation_id=opened["negotiation_id"], buyer_action=action,
            buyer_proposal=value, buyer_reason=None, buyer_principal=fixture._BUYER,
            seller_principal=fixture._SELLER, actor_principal=fixture._BUYER, actor_role="buyer",
        )
    counter = await continue_("counter", revised)
    assert counter["action"] == "counter"
    assert counter["proposal"]["fields"]["amount"] == "10000"
    buyer_decision, _ = bisection_middleware([
        NegotiationRound(round_number=0, sender="them", action="counter", proposal=counter["proposal"]),
    ], NegotiationContext(direction="minimize", our_reference_amount=10000))
    assert buyer_decision.action == "accept"
    accepted = await continue_(buyer_decision.action, buyer_decision.proposal)
    expected = math.ceil(Fraction(hourly * 9 * 1801, 10 * 3600))
    assert accepted["action"] == "accept"
    assert int(accepted["accepted_escrow_proposal"]["fields"]["amount"]) == expected
    assert accepted["agreement"].amount == expected
    assert accepted["settlement_plan"]["obligations"][0]["amount"] == str(expected)
    fresh = type(db)(db_path=db.db_path, registry=db.domain_registry)
    messages = await fresh.load_negotiation_thread(negotiation_id=opened["negotiation_id"])
    assert int(messages[-1]["proposed_price"]) == 10000
    row = await fresh.load_negotiation_thread_row(negotiation_id=opened["negotiation_id"])
    assert json.loads(row["agreement_bytes"])["amount"] == str(expected)
    codec = amount_codec(listing, proposal(10000))
    assert codec.scalar_from_price(hourly) == 10000
    assert codec.payment_from_scalar(10000, accepted["agreement"].provision_terms) == expected


@pytest.mark.parametrize("ttl,with_gpu", [(900, True), (0, False)])
async def test_smaller_agreed_shape_reaches_the_committed_reservation(db, site_app, ttl, with_gpu):
    app, ledger = site_app
    ledger.register_resource(
        resource_id="resource-hook", pool_id="default", host_id="host-hook",
        capacity={"gpu_count": 1, "vcpu_count": 8},
        attributes={"gpu_model": "H200", "region": "California, US"},
    )
    client = _client(app)

    capacity = CapacityRuntime(
        sites=(CapacitySite("site-test", "http://test", SITE_AUTHORITIES),),
        signer=fixture._SELLER_SIGNER, placement=fill_first,
        reconcile=fixture._noop_reconcile,
        site_client_factory=lambda _site, _signer: client,
    )
    listing, runtime, proposal = await prepare(db, capacity_runtime=capacity)
    with settings_overrides(**{"capacity.hold_ttl_seconds": ttl}):
        opened = await runtime().start(
            repository=db, listing_id="L-hook", buyer_principal=fixture._BUYER,
            seller_principal=fixture._SELLER, actor_principal=fixture._BUYER,
            proposal=proposal(9000), terms=make_vm_provision_terms(
                duration_seconds=3600, ssh_public_key="ssh-ed25519 public-development-fixture",
            ), seller_agent_url="http://seller.test", buyer_agent_url="http://buyer.test",
        )
        revised = proposal(9500)
        shape = {"cpu": {"count": 2}}
        if with_gpu:
            shape["gpu"] = {"model": "H200", "count": 1}
        revised["provision_terms"] = {"kind": "compute.v1", "version": 1, "payload": shape}
        async def continue_(action, value):
            return await runtime().continue_negotiation(
                repository=db, negotiation_id=opened["negotiation_id"], buyer_action=action,
                buyer_proposal=value, buyer_reason=None, buyer_principal=fixture._BUYER,
                seller_principal=fixture._SELLER, actor_principal=fixture._BUYER, actor_role="buyer",
            )
        counter = await continue_("counter", revised)
        accepted = await continue_("accept", counter["proposal"])
    assert accepted["action"] == "accept"
    expected = {"vcpu_count": 2, **({"gpu_count": 1} if with_gpu else {})}
    order = accepted["settlement_plan"]["service_terms"]["vm.v1"]["order"]
    assert compute_capacity_claim_from_order(order)["dimensions"] == expected
    fresh = type(db)(db_path=db.db_path, registry=db.domain_registry)
    row = await fresh.load_negotiation_thread_row(negotiation_id=opened["negotiation_id"])
    assert row["settlement_plan"]["service_terms"]["vm.v1"]["order"] == order
    current = await fresh.load_listing(listing_id="L-hook")
    assert json.loads(current["listing_resource"])["vcpu_count"] == 4
    evidence = vm_evidence(
        raw=row["agreement_bytes"], mechanism="alkahest.v1", reference="fixture-escrow",
        source={"escrow_uid": "fixture-escrow"},
        facts=delivery_facts(json.loads(row["agreement_bytes"]), order),
    )
    plan = build_vm_fulfillment_plan(evidence=evidence)
    assert plan.required_attributes["dimensions"] == expected
    hold = await fresh.load_capacity_hold(negotiation_id=opened["negotiation_id"])
    if ttl:
        assert ledger.get_reservation(hold["capacity_reservation_id"])["dimensions"] == expected
    else:
        assert hold is None
    await fresh.save_vm_settlement_evidence(evidence)
    domain = VmDeliveryDomain(
        fresh, stages={}, payments=None, fulfillment=SimpleNamespace(),
    )
    claim = await domain.reserve_claim(opened["negotiation_id"])
    assert claim.claim["dimensions"] == expected
    binding = PublicationBinding("site-test", "vm", "pool-L-hook", BACKED)
    with transaction(fresh.db_path) as connection:
        register_delivery(connection, opened["negotiation_id"])
        window = agreement_window(EndSession(connection).read(opened["negotiation_id"]))
    accepted_hold = await domain.accepted_hold(opened["negotiation_id"])
    if accepted_hold is not None:
        reservation_id = accepted_hold.capacity_reservation_id
    else:
        reserved = await capacity.reserve(
            binding, claim=claim.claim, deal_ref=claim.deal_ref,
            lease_start_utc=window.start_utc, lease_duration_seconds=window.duration_seconds,
        )
        reservation_id = reserved["capacity_reservation_id"]
    await capacity.commit(
        binding, resource_id=None, capacity_reservation_id=reservation_id,
        lease_start_utc=window.start_utc, lease_end_utc=window.end_utc,
        deal_ref=claim.deal_ref,
    )
    committed = ledger.get_reservation(reservation_id)
    assert committed["state"] == "leased"
    assert committed["dimensions"] == expected


async def test_explicit_lower_floor_applies_to_an_unanticipated_shape(db):
    listing, runtime, proposal = await prepare(db)
    with settings_overrides(**{"negotiation.multiplier_floor_bps": 8000}):
        opened = await runtime().start(
            repository=db, listing_id="L-hook", buyer_principal=fixture._BUYER,
            seller_principal=fixture._SELLER, actor_principal=fixture._BUYER,
            proposal=proposal(7800), terms=make_vm_provision_terms(
                duration_seconds=3600, ssh_public_key="", compute_resource={"vcpu_count": 3},
            ), seller_agent_url="http://seller.test", buyer_agent_url="http://buyer.test",
        )
    assert opened["action"] == "counter"
    assert opened["proposal"]["fields"]["amount"] == "8000"


async def test_a_shape_larger_than_advertised_refuses_before_pricing(db):
    """The policy admits up to eight vCPUs, but no probe can confirm more than
    the four advertised."""
    hook = AsyncMock()
    _listing, runtime, proposal = await prepare(db, seller_round_hook=hook)
    with pytest.raises(OfferUnfulfillableError, match="^shape_exceeds_advertised: ") as refused:
        await runtime().start(
            repository=db, listing_id="L-hook", buyer_principal=fixture._BUYER,
            seller_principal=fixture._SELLER, actor_principal=fixture._BUYER,
            proposal=proposal(9000), terms=make_vm_provision_terms(
                duration_seconds=3600, ssh_public_key="", compute_resource={"vcpu_count": 6},
            ), seller_agent_url="http://seller.test", buyer_agent_url="http://buyer.test",
        )
    assert "vcpu_count" in refused.value.reason
    assert "gpu_count" not in refused.value.reason
    hook.assert_not_awaited()


async def test_a_revision_larger_than_advertised_refuses_and_the_thread_continues(db):
    hook = AsyncMock()
    _listing, runtime, proposal = await prepare(db, seller_round_hook=hook)
    hook.return_value = SellerRoundResult(
        our_amount=10_000, strategy_label="maximize", direction="maximize",
        chain_label="custom",
        decision=NegotiationDecision(action="counter", proposal=proposal(10_000)),
    )
    opened = await runtime().start(
        repository=db, listing_id="L-hook", buyer_principal=fixture._BUYER,
        seller_principal=fixture._SELLER, actor_principal=fixture._BUYER,
        proposal=proposal(9000), terms=make_vm_provision_terms(
            duration_seconds=3600, ssh_public_key="",
        ), seller_agent_url="http://seller.test", buyer_agent_url="http://buyer.test",
    )
    hook.reset_mock()

    async def revise(gpu_count):
        revised = proposal(9500)
        revised["provision_terms"] = {"kind": "compute.v1", "version": 1, "payload": {
            "gpu": {"model": "H200", "count": gpu_count}, "cpu": {"count": 2},
        }}
        return await runtime().continue_negotiation(
            repository=db, negotiation_id=opened["negotiation_id"], buyer_action="counter",
            buyer_proposal=revised, buyer_reason=None, buyer_principal=fixture._BUYER,
            seller_principal=fixture._SELLER, actor_principal=fixture._BUYER,
            actor_role="buyer",
        )

    with pytest.raises(OfferUnfulfillableError, match="^shape_exceeds_advertised: "):
        await revise(2)
    hook.assert_not_awaited()
    smaller = await revise(1)
    assert smaller["action"] == "counter"
    hook.assert_awaited_once()
    assert hook.await_args.kwargs["requested_shape"] == {
        "gpu": {"model": "H200", "count": 1}, "cpu": {"count": 2},
    }
