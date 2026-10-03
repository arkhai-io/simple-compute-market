"""Real Formance payment, controlled selected-site VM provider, actual process restart."""

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

from arkhai_vms import make_vm_provision_terms
from core_storefront.domain_registry import StorefrontThreadBinding
from domains.vms.buyer.arkhai_payments import VmArkhaiPaymentsBuyer
from market_core import ImmutableFulfillmentCapability
from market_storefront.arkhai_payments import VmArkhaiPaymentsStage
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.payment_settlement import VmPaymentsCoordinator
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.utils.sqlite_client import SQLiteClient
from smoke_common import BUYER, SELLER, PAYER, agreement, config, effect, crash


async def main(directory, phase):
    settings = config()

    async def deliver(*, context):
        assert context.site_id == "site-smoke"
        count = effect(directory, context.negotiation_id)
        assert count == 1
        return dict(
            negotiation_id=context.negotiation_id,
            escrow_uid=context.escrow_uid,
            site_id=context.site_id,
            state="fulfilled",
            fulfillment_id="vm-smoke",
            domain_result={"connection_details": "controlled VM provider"},
        )

    domain = replace(
        build_vm_storefront_domain(),
        fulfillment=ImmutableFulfillmentCapability(fulfill=deliver),
    )
    registry = build_vm_storefront_registry(domain)
    db = SQLiteClient(str(Path(directory) / "storefront.db"), registry=registry)
    stage = VmArkhaiPaymentsStage(settings)
    state_file = Path(directory) / "state.json"
    if phase == "crash":
        provision = make_vm_provision_terms(
            duration_seconds=3600, ssh_public_key="ssh-ed25519 smoke"
        ).model_dump(mode="json")
        accepted = agreement("vm-smoke-" + Path(directory).name, provision)
        raw = accepted.model_dump_json(exclude_none=True).encode()
        state_file.write_text(json.dumps({"id": accepted.negotiation_id}))
        mandate = stage.mandate_for_agreement(json.loads(raw))
        binding = prepare_vm_listing_binding(
            listing_id=accepted.listing_id,
            candidate={"site_id": "site-smoke", "pool_id": "pool-smoke"},
        )
        await db.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at=accepted.accepted_at,
            updated_at=accepted.accepted_at,
            offer_resource={
                "gpu_model": "H200",
                "gpu_count": 1,
                "virtualization_type": "vm",
            },
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="http://storefront.local",
            seller_principal=SELLER.identity,
        )
        thread_binding = StorefrontThreadBinding(
            negotiation_id=accepted.negotiation_id,
            listing_id=accepted.listing_id,
            site_id="site-smoke",
            binding=binding.binding,
        )
        await db.create_negotiation_thread(
            negotiation_id=accepted.negotiation_id,
            our_listing_id=accepted.listing_id,
            their_listing_id="",
            our_agent_id="seller",
            their_agent_id="buyer",
            buyer_principal=BUYER.identity,
            seller_principal=SELLER.identity,
            owner_id="seller",
            requested_duration_seconds=3600,
            provision_terms=provision,
            binding=thread_binding,
        )
        await db.commit_agreed_terms(
            negotiation_id=accepted.negotiation_id,
            agreed_price=100,
            agreed_duration_seconds=3600,
            agreement_bytes=raw,
            accepted_at=accepted.accepted_at,
            agreed_start_utc=accepted.start_utc,
            settlement_data={"mandate": mandate},
        )
        await db.update_negotiation_thread_terminal(
            negotiation_id=accepted.negotiation_id, terminal_state="success"
        )
    identifier = json.loads(state_file.read_text())["id"]
    thread = await db.load_negotiation_thread_row(negotiation_id=identifier)
    coordinator = VmPaymentsCoordinator(domain=domain, db=db, stage=stage)
    if phase == "crash":
        result = await coordinator.start(identifier, thread)
        assert result["status"] == "pending"
        VmArkhaiPaymentsBuyer(settings, PAYER).approve(
            agreement=thread["agreement_bytes"],
            settlement_data=thread["settlement_data"],
            timeout=10,
            interval=0.01,
        )
        result = await coordinator.start(identifier, thread)
        assert result["status"] == "provisioning"
        record = await db.load_vm_payment_record(negotiation_id=identifier)
        assert record["receipt"] is not None
        crash(
            "VM: approve -> poll -> receipt verified -> provisioning; exit before provider dispatch"
        )
    result = await coordinator.start(identifier, thread)
    await coordinator.tasks[identifier]
    repeated = await coordinator.start(identifier, thread)
    assert repeated["status"] == "ready", repeated
    assert effect(directory, identifier) == 1
    print("VM: restarted -> ready; repeated settle -> ready; deliveries=1")
    await coordinator.stop()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
