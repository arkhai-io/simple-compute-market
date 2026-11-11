"""Local VM payment-stage first use; payments HTTP and VM delivery are controlled.

Run from the repository root using the wheel setup in the adjacent README.md.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
from arkhai_vms import make_vm_provision_terms
from core_storefront.domain_registry import StorefrontThreadBinding
from fastapi import FastAPI
from market_arkhai_payments import (
    ArkhaiPaymentsConfig,
    PaymentApproval,
    PaymentSellerStage,
    PaymentSettlementData,
)
from market_arkhai_payments.fixtures import FakePaymentsClient, dispute_lifecycle
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_core import ImmutableFulfillmentCapability
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_deal_servicing import create_lifecycle_router, EndSession, PhysicalResult
from market_deal_servicing.evidence import transaction
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy
from market_storefront.deal_lifecycle import VmDealLifecycle
from storefront_client import StorefrontClient
from market_identity import (
    TrustedIdentitySet,
    REQUEST_PROTOCOL,
    Ed25519Signer,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)

import market_storefront.container as container
from market_storefront.controllers.settle_controller import router
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.payment_settlement import VmPaymentsCoordinator
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.services.vm_fulfillment_planner import build_vm_fulfillment_plan
from market_storefront.utils.migrations import migrate_storefront_database
from market_storefront.utils.sqlite_client import SQLiteClient

PAYER = "00000000-0000-4000-8000-000000000011"
PAYEE = "00000000-0000-4000-8000-000000000012"


async def main(*, end_before_delivery=False):
    service, buyer, seller = (Ed25519Signer(bytes([n]) * 32) for n in (11, 12, 13))
    # The kit's fake plays the payments service; its receipts come from the
    # vector-pinned fixture, so nothing here frames or signs a receipt itself.
    payments = FakePaymentsClient(signer=service)
    deliveries = []
    config = ArkhaiPaymentsConfig(
        enabled=True,
        service_url="http://127.0.0.1",
        service_identity=service.identity,
        fee_bps=250,
        development_auth=True,
    )

    async def deliver(*, context):
        plan = build_vm_fulfillment_plan(evidence=context.settlement_evidence)
        assert plan.provision_terms.ssh_public_key
        assert plan.order_id == context.thread_binding.listing_id
        deliveries.append(context.negotiation_id)
        await context.ports.repository.update_vm_delivery(
            negotiation_id=context.negotiation_id, fulfillment_id="vm-demo"
        )
        return {
            "negotiation_id": context.negotiation_id,
            "settlement_ref": context.settlement_ref,
            "site_id": context.site_id,
            "state": "fulfilled",
            "fulfillment_id": "vm-demo",
            "domain_result": {"connection_details": "local controlled VM"},
        }

    domain = replace(
        build_vm_storefront_domain(),
        fulfillment=ImmutableFulfillmentCapability(fulfill=deliver),
    )
    registry = build_vm_storefront_registry(domain)
    stage = PaymentSellerStage(config, client_for_owner=payments)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    params = {"payee_account": PAYEE, "window": "P7D", "deposit_agreement": False}
    option_body = {
        "price": {"asset": "USD/2", "rates": []},
        "settlement": {"schema": "arkhai.payments.v1", **(params or {})},
        "lifecycle": dispute_lifecycle(PAYER),
    }
    option_body["lifecycle"]["adjudication"]["dispute"] = MediationContractFake().authority
    option = SettlementOption(
        option_id=derive_settlement_option_id(**option_body), **option_body
    )
    provision = make_vm_provision_terms(
        duration_seconds=3600, ssh_public_key="ssh-ed25519 demo"
    ).model_dump(mode="json")
    agreement = Agreement(
        negotiation_id="payment-demo",
        listing_id="vm-demo",
        listing_hash="0" * 64,
        buyer=buyer.identity.model_dump(mode="json"),
        seller=seller.identity.model_dump(mode="json"),
        settlement=option,
        settlement_params={"payer_account": PAYER},
        amount=100,
        asset="USD/2",
        duration_seconds=3600,
        start_utc=now,
        accepted_at=now,
        provision_terms=provision,
    )
    raw = agreement.model_dump_json(exclude_none=True).encode()
    settlement_data = stage.settlement_data(json.loads(raw)).to_wire()

    with tempfile.TemporaryDirectory(prefix="vm-payment-demo-") as directory:
        db_path = Path(directory) / "storefront.db"
        migrate_storefront_database(db_path)
        db = SQLiteClient(str(db_path), registry=registry)
        binding = prepare_vm_listing_binding(
            listing_id="vm-demo",
            candidate={
                "capacity_backing": "backed",
                "site_id": "site-demo",
                "pool_id": "pool-demo",
                "resource_id": "resource-demo",
                "listing_shape": {"gpu": {"count": 1, "model": "H200"}},
            },
        )
        await db.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at=now,
            updated_at=now,
            listing_resource={
                "pool_id": "pool-demo",
                "gpu_model": "H200",
                "gpu_count": 1,
                "offering_mode": "vm",
            },
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="http://storefront.local",
            seller_principal=seller.identity,
        )
        thread_binding = StorefrontThreadBinding(
            negotiation_id="payment-demo",
            listing_id="vm-demo",
            site_id="site-demo",
            binding=binding.binding,
        )
        await db.create_negotiation_thread(
            negotiation_id="payment-demo",
            our_listing_id="vm-demo",
            their_listing_id="",
            our_agent_id="seller",
            their_agent_id="buyer",
            buyer_principal=buyer.identity,
            seller_principal=seller.identity,
            owner_id="seller",
            requested_duration_seconds=3600,
            provision_terms=provision,
            binding=thread_binding,
        )
        await db.commit_agreed_terms(
            negotiation_id="payment-demo",
            negotiated_scalar=100,
            agreed_duration_seconds=3600,
            agreement_bytes=raw,
            accepted_at=now,
            agreed_start_utc=now,
            settlement_data=settlement_data,
        )
        await db.update_negotiation_thread_terminal(
            negotiation_id="payment-demo", terminal_state="success"
        )
        coordinator = VmPaymentsCoordinator(domain=domain, db=db, stage=stage)
        lifecycle = VmDealLifecycle(db, seller, coordinator, RegistryDisputePolicy.from_document({}))
        coordinator.lifecycle = lifecycle

        class Physical:
            async def apply_end(self, *_args, **_kwargs):
                return PhysicalResult(progress="released" if not deliveries else "tearing_down", done=not deliveries)

        lifecycle.end.physical = Physical()
        container.resolved_sqlite_client = db
        container.resolved_marketplace_signer = seller
        container.resolved_settlement_composition = SimpleNamespace(
            payments_coordinator=coordinator,
            seller_stages=domain.settlement.seller_stages,
            local_principal=seller.identity,
            arkhai_payments_stage=stage,
            lifecycle=lifecycle,
        )
        app = FastAPI()
        app.include_router(router)
        app.include_router(create_lifecycle_router(lambda _: lifecycle.routes(
            TrustedIdentitySet(identities=(seller.identity,))
        )))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://storefront.local"
        ) as http:

            async def settle():
                body = {
                    "negotiation_id": "payment-demo",
                    "buyer_principal": buyer.identity.model_dump(mode="json"),
                }
                auth = sign_request(
                    signer=buyer,
                    envelope=RequestEnvelope(
                        role="buyer",
                        principal=buyer.identity,
                        method="POST",
                        operation="settle_escrow",
                        resource="payment-demo",
                        request_id=str(uuid.uuid4()),
                        timestamp=int(time.time()),
                        body_hash=canonical_body_hash(body),
                    ),
                )
                response = await http.post(
                    "/api/v1/settle/payment-demo",
                    json=body,
                    headers={
                        "X-Market-Signature-Version": REQUEST_PROTOCOL,
                        "X-Market-Identity-Scheme": auth.principal.scheme.value,
                        "X-Market-Identity-Identifier": auth.principal.identifier,
                        "X-Market-Role": auth.role,
                        "X-Market-Request-ID": auth.request_id,
                        "X-Market-Timestamp": str(auth.timestamp),
                        "X-Market-Signature": auth.proof.value,
                    },
                )
                response.raise_for_status()
                return response.json()

            assert (await settle())["status"] == "pending"
            assert deliveries == []
            PaymentApproval(config, PAYER, client_for_owner=payments).approve(
                raw, settlement_data, interval=0.01
            )
            if end_before_delivery:
                data = PaymentSettlementData.parse(settlement_data)
                checked = await stage.check_receipt(json.loads(raw), data)
                await coordinator._record_verified("payment-demo", raw, json.loads(raw), data, checked.receipt)
                async with StorefrontClient(
                    "http://storefront.local", signer=buyer, caller_role="buyer",
                    expected_publishers=TrustedIdentitySet(identities=(seller.identity,)),
                    transport=httpx.ASGITransport(app),
                ) as client:
                    receipt = await client.authenticated_request(
                        "POST", "/api/v1/negotiations/payment-demo/lifecycle", role="buyer",
                        operation="lifecycle_peer", resource="payment-demo",
                        body={"kind": "end_delivery", "negotiation_id": "payment-demo", "operation_key": "demo-end"},
                    )
                    assert receipt["delivery"]["progress"] == "released"
                    assert receipt["signed_delivery_end_claim"]["claim"]["delivered"] is True
                assert (await settle())["status"] == "ended"
                assert deliveries == []
                assert await db.load_vm_delivery(negotiation_id="payment-demo") is None
                with transaction(db.db_path) as conn:
                    assert len(EndSession(conn).requests("payment-demo")) == 1
                print("end before delivery: signed receipt; released; later settlement ended; zero dispatches")
                await lifecycle.close()
                await coordinator.stop()
                container.clear_lifespan_state(registry=registry)
                return
            assert (await settle())["status"] == "provisioning"
            await coordinator.tasks["payment-demo"]
            assert (await settle())["status"] == "ready"
            with sqlite3.connect(db.db_path) as sql:
                escrow_count = sql.execute("SELECT COUNT(*) FROM escrows").fetchone()[0]
                print("payment escrow rows:", escrow_count)
                assert escrow_count == 0
            assert deliveries == ["payment-demo"]
            async with StorefrontClient(
                "http://storefront.local", signer=seller, caller_role="admin",
                expected_publishers=TrustedIdentitySet(identities=(seller.identity,)),
                transport=httpx.ASGITransport(app),
            ) as administrator:
                page = await administrator.authenticated_request(
                    "GET", "/api/v1/admin/lifecycle", role="admin",
                    operation="lifecycle_list", resource="",
                )
                assert [deal["negotiation_id"] for deal in page["deals"]] == ["payment-demo"]
                print("lifecycle list:", page["deals"][0]["mechanism"])
            kind, outcome, progress = await lifecycle.interrupt(
                "payment-demo", actor=seller.identity, operation_key="demo-admin-end",
                reason="development hardware withdrawal",
            )
            assert kind == "delivery_end"
            assert progress.progress == "tearing_down"
            with transaction(db.db_path) as conn:
                end = EndSession(conn)
                request = end.selected_end("payment-demo")
                assert request.actor == seller.identity
                assert request.administrator_reason == "development hardware withdrawal"
                filings = [intent for intent in end.intents("payment-demo") if intent.kind == "filing"]
                assert len(filings) == 1
                assert filings[0].payload["payload"]["cause"] == "payee"
            retry = await lifecycle.interrupt(
                "payment-demo", actor=seller.identity, operation_key="demo-admin-end",
                reason="development hardware withdrawal",
            )
            assert retry[0] == kind
            print("administrator exceptional end:", progress.progress, "filing:", outcome.status,
                  "same-key retry retains one filing")
        await lifecycle.close()
        await coordinator.stop()
        container.clear_lifespan_state(registry=registry)


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(main(end_before_delivery=True))
