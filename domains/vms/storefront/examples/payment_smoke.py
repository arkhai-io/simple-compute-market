"""Local VM payment-stage first use; payments HTTP and VM delivery are controlled.

Run from the repository root using the wheel setup in the adjacent README.md.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from arkhai_vms import make_vm_provision_terms
from core_storefront.domain_registry import StorefrontThreadBinding
from domains.vms.buyer.arkhai_payments import VmArkhaiPaymentsBuyer
from fastapi import FastAPI
from market_arkhai_payments import (
    ArkhaiPaymentsConfig,
    PaymentsClient,
    SignedReceipt,
    transaction_id,
)
from market_arkhai_payments.canonical import jcs_sha256
from market_core import ImmutableFulfillmentCapability
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import (
    REQUEST_PROTOCOL,
    Ed25519Signer,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)
from market_identity.canonical import _frame

import market_storefront.container as container
from market_storefront.arkhai_payments import VmArkhaiPaymentsStage
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
    approved = {}
    deliveries = []

    def payments_http(request):
        if request.method == "POST":
            mandate = json.loads(request.content)["mandate"]
            receipt = {
                "transaction": transaction_id(mandate),
                "deal": mandate["deal"],
                "from": mandate["from"],
                "to": mandate["to"],
                "ledger": "local-demo",
                "parts": [
                    {
                        "asset": "USD/2",
                        "gross": "100",
                        "fee": "2",
                        "net": "98",
                        "hold": mandate["parts"][0]["hold"],
                    }
                ],
                "approvedAt": int(time.time()),
                "issuer": service.identity.model_dump(mode="json"),
            }
            signature = service.sign(
                _frame(("arkhai.payments.receipt.v1", jcs_sha256(receipt)))
            )
            signed = SignedReceipt.model_validate(
                {
                    "receipt": receipt,
                    "proof": {
                        "scheme": "ed25519",
                        "value": base64.urlsafe_b64encode(signature)
                        .decode()
                        .rstrip("="),
                    },
                }
            ).model_dump(mode="json", by_alias=True, exclude_none=True)
            approved["receipt"] = signed
            return httpx.Response(200, json=signed)
        if not approved:
            return httpx.Response(404, json={"error": "transaction_not_found"})
        receipt = approved["receipt"]
        snapshot = {
            "transaction": receipt["receipt"]["transaction"],
            "receipt": receipt,
            "observedAt": int(time.time()),
            "events": [],
            "attachments": [],
            "issuer": service.identity.model_dump(mode="json"),
            "parts": [
                {
                    "part": 0,
                    "asset": "USD/2",
                    "gross": "100",
                    "held": "100",
                    "released": "0",
                    "reversed": "0",
                    "feePaid": "0",
                    "hold": receipt["receipt"]["parts"][0]["hold"],
                    "status": "held",
                }
            ],
        }
        return httpx.Response(
            200, json={"snapshot": snapshot, "proof": receipt["proof"]}
        )

    transport = httpx.MockTransport(payments_http)
    config = ArkhaiPaymentsConfig(
        enabled=True,
        service_url="http://127.0.0.1",
        service_identity=service.identity,
        fee_bps=250,
        dispute_authority=PAYER,
        development_auth=True,
    )

    def client_for_owner(config, owner):
        return PaymentsClient(
            config.service_url, development_account=owner, transport=transport
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
    stage = VmArkhaiPaymentsStage(config)
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
    mandate = stage.mandate_for_agreement(json.loads(raw))

    with (
        tempfile.TemporaryDirectory(prefix="vm-payment-demo-") as directory,
        patch(
            "market_storefront.arkhai_payments.payments_client_for_owner",
            client_for_owner,
        ),
        patch(
            "domains.vms.buyer.arkhai_payments.payments_client_for_owner",
            client_for_owner,
        ),
    ):
        db = SQLiteClient(str(Path(directory) / "storefront.db"), registry=registry)
        binding = prepare_vm_listing_binding(
            listing_id="vm-demo",
            candidate={"site_id": "site-demo", "pool_id": "pool-demo"},
        )
        await db.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at=now,
            updated_at=now,
            offer_resource={
                "pool_id": "pool-demo",
                "gpu_model": "H200",
                "gpu_count": 1,
                "virtualization_type": "vm",
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
            settlement_data={"mandate": mandate},
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
            VmArkhaiPaymentsBuyer(config, PAYER).approve(
                agreement=raw, settlement_data=mandate, interval=0.01
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
