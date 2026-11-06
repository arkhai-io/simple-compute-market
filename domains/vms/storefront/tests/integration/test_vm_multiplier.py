"""VM multiplier arithmetic and durable shape-independent concession behavior."""
from __future__ import annotations

import json
import math
from fractions import Fraction

from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.negotiation_amounts import amount_codec
from market_core.schemas import ProvisionTerms, derive_settlement_option_id
from market_policy.negotiation_middleware import NegotiationContext, NegotiationRound
from market_policy.scalar_policies import bisection_middleware
from market_storefront.negotiation_runtime import build_vm_negotiation_runtime
from tests._settings_overrides import settings_overrides
from tests.fake_site import FakeProjectionSite, loaded_site_projection_state
from tests.unit.test_sync_negotiation_seller_round_hook import db, marketplace_dependencies
from tests.unit import test_sync_negotiation_seller_round_hook as fixture


async def prepare(db, hourly=100):
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
        rate_structure={
            "gpu": [{"asset": fixture._TOKEN, "rate": "60", "per": "hour"}],
            "cpu": [{"asset": fixture._TOKEN, "rate": "10", "per": "hour"}],
        },
    )
    state = await loaded_site_projection_state({"site-test": FakeProjectionSite(resource_pools=[{
        "pool_id": "pool-L-hook", "pool_metadata": {"policy_tags": {"listing_shapes": {"vm": [{
            "gpu": {"model": "H200", "count": 1}, "cpu": {"count": {"offer": 4, "max": 8}},
        }]}}},
    }])})
    registration = db.domain_registry.resolve_mode("vm")
    def runtime():
        return build_vm_negotiation_runtime(
            registration.contract, registry=db.domain_registry, binding=registration.binding,
            capacity_runtime=fixture._capacity_runtime(), site_projections=state,
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
        "gpu": {"model": "H200", "count": 1}, "cpu": {"count": 6},
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
    expected = math.ceil(Fraction(hourly * 6 * 1801, 5 * 3600))
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


async def test_explicit_lower_floor_applies_to_an_unanticipated_shape(db):
    listing, runtime, proposal = await prepare(db)
    with settings_overrides(**{"negotiation.multiplier_floor_bps": 8000}):
        opened = await runtime().start(
            repository=db, listing_id="L-hook", buyer_principal=fixture._BUYER,
            seller_principal=fixture._SELLER, actor_principal=fixture._BUYER,
            proposal=proposal(7800), terms=make_vm_provision_terms(
                duration_seconds=3600, ssh_public_key="", compute_resource={"vcpu_count": 7},
            ), seller_agent_url="http://seller.test", buyer_agent_url="http://buyer.test",
        )
    assert opened["action"] == "counter"
    assert opened["proposal"]["fields"]["amount"] == "8000"
