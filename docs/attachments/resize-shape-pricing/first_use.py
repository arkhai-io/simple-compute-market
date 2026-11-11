"""Fixture-backed negotiation surface for reproducing the slice-A encounter."""
import asyncio
import json
import tempfile
from pathlib import Path
from pytest import MonkeyPatch
from market_capability_admissibility import parse_declaration
from arkhai_vms import VM_CAPABILITY_SCHEMA
from market_core.schemas import ProvisionTerms
from market_pool_overrides import PoolOverrideRecord, SQLitePoolOverrideStore
from market_storefront import container
from market_storefront.negotiation_runtime import build_vm_negotiation_runtime
from market_negotiation_runtime import OfferUnfulfillableError
from arkhai_vms_negotiation.amounts import quote_from_multiplier
from market_policy.scalar_policies import pinned_proposal
from tests.fake_site import FakeProjectionSite, loaded_site_projection_state
from tests.unit import test_sync_negotiation_seller_round_hook as fixture

async def main():
    with tempfile.TemporaryDirectory() as directory, MonkeyPatch.context() as patch:
        root = Path(directory)
        fixture.marketplace_dependencies.__wrapped__(patch)
        # The fixture yields its store inside the configured registries' scope.
        store = fixture.db.__wrapped__(root, patch)
        db = await anext(store)
        try:
            await encounter(db, patch)
        finally:
            await store.aclose()

async def encounter(db, patch):
    record = await db.load_listing(listing_id="L-hook")
    resource = {**json.loads(record["listing_resource"]), "vcpu_count": 4}
    structure = {
        "gpu": [
            {"asset": fixture._TOKEN, "rate": "60", "per": "hour"},
            {"asset": "usd", "rate": "9999", "per": "hour"},
        ],
        "cpu": [{"asset": fixture._TOKEN, "rate": "10", "per": "hour"}],
    }
    await db.update_listing(
        listing_id="L-hook", listing_resource=resource, rate_structure=structure,
    )
    # The seller prices from what its registries last accepted, so stored rates
    # take effect once a successful publication of them is recorded.
    await fixture._record_publish(db, structure)
    site = FakeProjectionSite(resource_pools=[{
        "pool_id": "pool-L-hook",
        "pool_metadata": {"policy_tags": {"listing_shapes": {"vm": [{
            "gpu": {"model": "H200", "count": 1},
            "cpu": {"count": {"offer": 4, "max": 8}},
        }]}}},
    }])
    state = await loaded_site_projection_state({"site-test": site})
    registration = db.domain_registry.resolve_mode("vm")
    references = []

    async def policy(**kwargs):
        result = await fixture._default_seller_round_hook(registration.contract)(**kwargs)
        references.append({
            "shape": kwargs["requested_shape"],
            "reference": result.our_amount,
            "quote": quote_from_multiplier(
                kwargs["listing"], pinned_proposal(kwargs["history"]), result.our_amount,
                kwargs["requested_duration_seconds"], kwargs["requested_shape"],
            ),
        })
        return result

    def runtime():
        return build_vm_negotiation_runtime(
            registration.contract, registry=db.domain_registry,
            binding=registration.binding, capacity_runtime=fixture._capacity_runtime(),
            site_projections=state, seller_round_hook=policy,
            listing_source_check=fixture._source_matches,
        )

    async def opening(compute):
        return await runtime().start(
            repository=db, listing_id="L-hook",
            buyer_principal=fixture._BUYER, seller_principal=fixture._SELLER,
            actor_principal=fixture._BUYER, proposal=fixture._selected_proposal(9000),
            terms=ProvisionTerms(kind="compute.v1", version=1, payload={
                "duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 public-development-fixture",
                "compute_resource": compute,
            }),
            seller_agent_url="http://seller.test", buyer_agent_url="http://buyer.test",
        )

    async def continuation(opened, revision=None, action="counter"):
        proposal = fixture._selected_proposal(9500)
        if revision is not None:
            proposal["provision_terms"] = {
                "kind": "compute.v1", "version": 1, "payload": revision,
            }
        return await runtime().continue_negotiation(
            repository=db, negotiation_id=opened["negotiation_id"],
            buyer_action=action, buyer_proposal=proposal if action != "exit" else None,
            buyer_reason=None, buyer_principal=fixture._BUYER,
            seller_principal=fixture._SELLER, actor_principal=fixture._BUYER, actor_role="buyer",
        )

    first = await opening({"vcpu_count": 2})
    print("opening", json.dumps({"action": first["action"], "reference": references[-1]}))
    await continuation(first, {"gpu": {"model": "H200", "count": 1}, "cpu": {"count": 6}})
    print("revised", json.dumps(references[-1]))
    await continuation(first)
    print("resumed_without_revision", json.dumps(references[-1]))
    # Repeated floor counters reach the policy's stale exit. Use a new
    # live thread for the remaining refusal and withdrawal encounters.
    first = await opening({"vcpu_count": 2})

    for label, compute in [
        ("outside_hint_and_wrong_model", {"vcpu_count": 9, "gpu_model": "A100"}),
        ("wrong_model", {"gpu_model": "A100"}),
        ("wrong_region", {"region": "Tokyo, JP"}),
    ]:
        calls = len(references)
        try:
            await opening(compute)
        except OfferUnfulfillableError as exc:
            print(label, str(exc), "pricing_calls", len(references) - calls)

    try:
        await continuation(first, {"storage": {"gib": 1}})
    except OfferUnfulfillableError as exc:
        print("unpriceable_shape", str(exc))

    default = parse_declaration(
        {"cpu": {"count": {"max": 5}}}, tier="configured_default", schema=VM_CAPABILITY_SCHEMA,
    ).declaration
    patch.setattr(container, "resolved_admissibility_default", default)
    await opening({"vcpu_count": 7})
    print("hint_over_default", json.dumps(references[-1]))
    override = SQLitePoolOverrideStore(db.db_path)
    await override.replace(PoolOverrideRecord(
        site_id="site-test", pool_id="pool-L-hook", offering_mode="vm",
        listing_shapes=[{
            "gpu": {"model": "H200", "count": 1},
            "cpu": {"count": {"offer": 4, "max": 6}},
        }],
    ))
    try:
        await opening({"vcpu_count": 7})
    except OfferUnfulfillableError as exc:
        print("override_replaces_hint", str(exc))
    await override.replace(PoolOverrideRecord(
        site_id="site-test", pool_id="pool-L-hook", offering_mode="vm",
        listing_shapes=[{"gpu": {"model": "H200", "count": 1}, "cpu": {"count": 4}}],
    ))
    try:
        await opening({"vcpu_count": 6})
    except OfferUnfulfillableError as exc:
        print("default_fills_override", str(exc))
    try:
        await continuation(first, {"cpu": {"count": 9}})
    except OfferUnfulfillableError as exc:
        print("continuation_before_fallback_pricing", str(exc))

    # Leaving remains possible when the persisted shape cannot now be priced.
    # Withdrawing the rates is a publication without them, as the seller's
    # registries would last have accepted it.
    await db.update_listing(listing_id="L-hook", rate_structure=None)
    await fixture._record_publish(db, None)
    print("exit_after_rates_withdrawn", (await continuation(first, action="exit"))["action"])
    try:
        await opening({"vcpu_count": 3})
    except OfferUnfulfillableError as exc:
        print("flat_priced_shape_fixed", str(exc))
    print("authoritative_requested_shape_probe", "not checked")

asyncio.run(main())
