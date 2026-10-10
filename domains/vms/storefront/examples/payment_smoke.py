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
)
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_core import ImmutableFulfillmentCapability
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import (
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
from market_storefront.utils.sqlite_client import SQLiteClient

PAYER = "00000000-0000-4000-8000-000000000011"
PAYEE = "00000000-0000-4000-8000-000000000012"


async def main():
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
        dispute_authority=PAYER,
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
    params = {
        "payee_account": PAYEE,
        "asset": "USD/2",
        "window": "P7D",
        "deposit_agreement": False,
    }
    option_body = {
        "mechanism": "arkhai.payments.v1",
        "asset": "USD/2",
        "rates": [],
        "params": params,
    }
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
        db = SQLiteClient(str(Path(directory) / "storefront.db"), registry=registry)
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
            agreed_price=100,
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
        container.resolved_sqlite_client = db
        container.resolved_marketplace_signer = seller
        container.resolved_settlement_composition = SimpleNamespace(
            payments_coordinator=coordinator,
            seller_stages=domain.settlement.seller_stages,
            local_principal=seller.identity,
            arkhai_payments_stage=stage,
        )
        app = FastAPI()
        app.include_router(router)
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

            print(
                "before approval:",
                (await settle())["status"],
                "deliveries:",
                len(deliveries),
            )
            PaymentApproval(config, PAYER, client_for_owner=payments).approve(
                raw, settlement_data, interval=0.01
            )
            print("after approval:", (await settle())["status"])
            await coordinator.tasks["payment-demo"]
            print("retry:", (await settle())["status"], "deliveries:", len(deliveries))
            with sqlite3.connect(db.db_path) as sql:
                escrow_count = sql.execute("SELECT COUNT(*) FROM escrows").fetchone()[0]
                print("payment escrow rows:", escrow_count)
                assert escrow_count == 0
            assert deliveries == ["payment-demo"]
        await coordinator.stop()
        container.clear_lifespan_state(registry=registry)


if __name__ == "__main__":
    asyncio.run(main())
