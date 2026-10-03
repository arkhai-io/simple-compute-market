"""Real-ledger receipt gate, controlled hardware, persisted process restart."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from arkhai_bare_metal import BareMetalListing, BareMetalMessage, BareMetalTerms
from arkhai_bare_metal_buyer.arkhai_payments import BareMetalArkhaiPaymentsBuyer
from arkhai_bare_metal_storefront.arkhai_payments import BareMetalArkhaiPaymentsStage
from arkhai_bare_metal_storefront.fulfillment_service import (
    BareMetalFulfillmentService,
    BareMetalFulfillmentError,
)
from arkhai_bare_metal_storefront.models import BareMetalSettleRequest
from arkhai_bare_metal_storefront.settlement_service import BareMetalSettlementService
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from market_fulfillment import VersionedEnvelope
from smoke_common import BUYER, SELLER, PAYER, agreement, config, crash, effect


class Capacity:
    reservation_sites = {}

    def site(self, site_id):
        assert site_id == "site-smoke"
        return self

    async def list_reservations(self):
        return []

    async def reserve(self, **request):
        assert request["site"] == "site-smoke"
        return {"capacity_reservation_id": "reservation-smoke", "site": "site-smoke"}


class Provider:
    def __init__(self, directory, phase):
        self.directory, self.phase = directory, phase

    async def schedule_resource(self, request):
        return SimpleNamespace(
            settlement_resource_id="resource-smoke",
            pool_id="pool-smoke",
            resource_kind="compute.bare-metal",
            provider="bare_metal.ansible",
            attributes={
                "bare_metal_publication": {
                    "enabled": True,
                    "machine_id": "machine-smoke",
                    "physical_host_id": "host-smoke",
                }
            },
        )

    async def begin_fulfillment(self, request):
        if self.phase == "crash":
            crash(
                "Bare metal: approve -> poll -> receipt verified -> scheduled; exit before provider dispatch"
            )
        assert effect(self.directory, "bare-metal-delivery") == 1
        return SimpleNamespace(
            fulfillment_id="fulfillment-smoke", state="dispatch_pending"
        )

    async def get_fulfillment_status(self, identity, **request):
        return SimpleNamespace(
            state="active", failure_reason=None, failure_message=None
        )

    async def get_fulfillment_result(self, identity, **request):
        return VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={
                "fulfillment_id": identity,
                "capacity_reservation_id": "reservation-smoke",
                "state": "active",
                "provisioned_resources": [],
                "domain_result": {
                    "kind": "bare_metal.fulfillment.result.v1",
                    "schema_version": 1,
                    "payload": {
                        "kind": "bare_metal.v1",
                        "action": "node_grant_access",
                        "machine_id": "machine-smoke",
                        "physical_host_id": "host-smoke",
                        "ssh_user": "tenant-smoke",
                        "status": "success",
                    },
                },
            },
        )


async def main(directory, phase):
    settings = config()
    db = SQLiteClient(str(Path(directory) / "storefront.db"))
    stage = BareMetalArkhaiPaymentsStage(settings)
    identifier = "bm-smoke-" + Path(directory).name
    if phase == "crash":
        terms = BareMetalTerms(
            machine_id="machine-smoke",
            physical_host_id="host-smoke",
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 smoke",
            listing_ref="listing-smoke",
        )
        accepted = agreement(identifier, terms.model_dump(mode="json"))
        raw = accepted.model_dump_json(exclude_none=True).encode()
        mandate = stage.mandate_for_agreement(json.loads(raw))
        await db.upsert_bare_metal_listing(
            listing_id="listing-smoke",
            status="open",
            created_at=accepted.accepted_at,
            updated_at=accepted.accepted_at,
            seller_principal=SELLER.identity,
            storefront_url="http://storefront.local",
            listing=BareMetalListing(
                machine_id="machine-smoke",
                physical_host_id="host-smoke",
                capabilities={"gpu_model": "H200"},
            ),
            accepted_escrows=[],
            settlement_options=[accepted.settlement.model_dump(mode="json")],
            site_id="site-smoke",
            pool_id="pool-smoke",
            physical_resource_id="physical-smoke",
        )
        await db.persist_bare_metal_opening(
            negotiation_id=identifier,
            listing_id="listing-smoke",
            seller_principal=SELLER.identity,
            buyer_agent_id="buyer",
            buyer_principal=BUYER.identity,
            seller_reference_amount=100,
            strategy="smoke",
            message=BareMetalMessage(
                duration_seconds=3600, ssh_public_key="ssh-ed25519 smoke"
            ),
            proposal={},
            buyer_amount=100,
            seller_action="accept",
            seller_amount=100,
            terms=terms,
            agreed_amount=100,
            agreement_bytes=raw,
            accepted_at=accepted.accepted_at,
            settlement_data=mandate,
            settlement_mechanism="arkhai.payments.v1",
        )
    settlement = BareMetalSettlementService(
        db=db,
        seller_wallet=None,
        chain_clients={},
        chain_config_paths={},
        build_plan=None,
        verify_escrow=None,
        settlement_runtime=None,
        arkhai_payments_stage=stage,
    )
    request = BareMetalSettleRequest(
        negotiation_id=identifier, buyer_principal=BUYER.identity
    )
    fulfillment = BareMetalFulfillmentService(
        db, Capacity(), Provider(directory, phase)
    )
    if phase == "crash":
        pending = await settlement.verify(
            escrow_uid=identifier, request=request, buyer_principal=BUYER.identity
        )
        assert pending.status == "settlement_pending"
        try:
            await fulfillment.begin(
                negotiation_id=identifier, buyer_principal=BUYER.identity
            )
        except BareMetalFulfillmentError:
            pass
        else:
            raise AssertionError("delivery bypassed receipt gate")
        thread = await db.load_negotiation_thread_row(negotiation_id=identifier)
        BareMetalArkhaiPaymentsBuyer(settings, PAYER).approve(
            agreement=json.loads(thread["agreement_bytes"]),
            settlement_data=thread["settlement_data"],
            timeout=10,
            interval=0.01,
        )
    verified = await settlement.verify(
        escrow_uid=identifier, request=request, buyer_principal=BUYER.identity
    )
    assert verified.escrow_uid != identifier
    await fulfillment.begin(negotiation_id=identifier, buyer_principal=BUYER.identity)
    ready = await fulfillment.status(
        negotiation_id=identifier, buyer_principal=BUYER.identity
    )
    assert ready["state"] == "active"
    repeated = await settlement.verify(
        escrow_uid=identifier, request=request, buyer_principal=BUYER.identity
    )
    assert repeated == verified
    await fulfillment.begin(negotiation_id=identifier, buyer_principal=BUYER.identity)
    assert effect(directory, "bare-metal-delivery") == 1
    assert (
        await db.load_bare_metal_receipt(negotiation_id=identifier)
    ).status == "ready"
    print(
        "Bare metal: restarted -> active/ready receipt; repeated settle and delivery -> same identity; deliveries=1"
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
