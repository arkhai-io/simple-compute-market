"""Real payment ledger and HTTP credit authority; storefront restart and grant replay."""

import asyncio
import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
from market_arkhai_payments import (
    PaymentsClient,
    check,
    derive_mandate,
    transaction_id,
    verify_receipt,
)
from market_core import ImmutableFulfillmentCapability
from apicredits_storefront import container
from apicredits_storefront.controllers.settle_controller import SettleController
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest
from apicredits_storefront.utils.sqlite_client import SQLiteClient
from domains.apicredits.settlement import (
    ApiCreditsArkhaiPaymentsConfig,
    mandate_policy_from_agreement,
)
from domains.apicredits.settlement.credits_client import CreditsServiceClient
from domains.apicredits.listings.models import coerce_resource_dict
from domains.apicredits.settlement.fulfillment import fulfill_api_credits_obligation
from smoke_common import BUYER, SELLER, PAYER, PAYEE, URL, agreement, config, crash


async def main(directory, phase, authority):
    settings = config()
    response = httpx.get("http://127.0.0.1:3181/health", trust_env=False)
    response.raise_for_status()
    db = SQLiteClient(str(Path(directory) / "storefront.db"))
    identifier = "api-smoke-" + Path(directory).name
    payment_config = ApiCreditsArkhaiPaymentsConfig(
        enabled=True,
        account_id=PAYEE,
        service_url=URL,
        development_account=PAYEE,
        fee_bps=settings.fee_bps,
        dispute_authority=settings.dispute_authority,
        service_identity=settings.service_identity,
    )
    credits_client = CreditsServiceClient(
        "http://127.0.0.1:3181",
        Path(authority, "admin-key").read_text(),
        transport=httpx.AsyncHTTPTransport(),
    )

    async def deliver(**request):
        assert request["authoritative_gate"] == "payments_receipt_verified"
        if phase == "crash":
            crash(
                "API credits: approve -> poll -> receipt verified; exit before issuance dispatch"
            )
        result = await fulfill_api_credits_obligation(
            client=None,
            escrow_uid=request["escrow_uid"],
            mechanism=request["mechanism"],
            authoritative_gate=request["authoritative_gate"],
            offer_resource=coerce_resource_dict(request["order"]["offer_resource"]),
            quantity=request["quantity"],
            key_mode=request["key_mode"],
            key_id=request["key_id"],
            buyer_principal=request["buyer_principal"],
            listing_id=request["listing_id"],
            credits_client=credits_client,
            stage_event=lambda *a, **kw: None,
        )
        assert result["status"] == "fulfilled", result.get("message")
        if phase == "lost":
            crash(
                "API credits: authority committed one grant; exit before storefront acknowledgement"
            )
        return result

    domain = replace(
        get_market_domain_contract(),
        fulfillment=ImmutableFulfillmentCapability(fulfill=deliver),
    )
    payments_client = PaymentsClient(URL, development_account=PAYEE)
    container.resolved_settlement_composition = SimpleNamespace(
        domain=domain,
        payments_client=payments_client,
        settlement_config=SimpleNamespace(mechanism_config=lambda key: payment_config),
    )
    if phase == "crash":
        provision = {
            "kind": "api_credits.v1",
            "schema_version": 1,
            "payload": {"quantity": 10, "key_mode": "new"},
        }
        accepted = agreement(identifier, provision, duration=0)
        raw = accepted.model_dump_json(exclude_none=True).encode()
        wire = json.loads(raw)
        policy = mandate_policy_from_agreement(
            wire, fee_bps=settings.fee_bps, dispute_authority=settings.dispute_authority
        )
        mandate = derive_mandate(wire, policy)
        await db.upsert_listing(
            listing_id="listing-smoke",
            status="open",
            created_at=accepted.accepted_at,
            updated_at=accepted.accepted_at,
            offer_resource={
                "service_name": "smoke",
                "resource_id": "credits-smoke",
                "base_url": "http://api.local",
            },
            fulfillment_resource=None,
            max_duration_seconds=None,
            storefront_url="http://storefront.local",
            seller_principal=SELLER.identity,
        )
        await db.create_negotiation_thread(
            negotiation_id=identifier,
            our_listing_id="listing-smoke",
            their_listing_id="",
            our_agent_id="seller",
            their_agent_id="buyer",
            buyer_principal=BUYER.identity,
            seller_principal=SELLER.identity,
            owner_id="seller",
            provision_terms=provision,
        )
        await db.commit_agreed_terms(
            negotiation_id=identifier,
            agreed_price=100,
            agreed_duration_seconds=0,
            agreement_bytes=raw,
            accepted_at=accepted.accepted_at,
            agreed_start_utc=accepted.start_utc,
            settlement_data={
                "mandate": mandate.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                "transaction_id": transaction_id(mandate),
            },
        )
        await db.save_credit_terms(
            negotiation_id=identifier, quantity=10, key_mode="new"
        )
        await db.update_negotiation_thread_terminal(
            negotiation_id=identifier, terminal_state="success"
        )
        controller = SettleController(db=db, settlement_coordinator=None)
        request = ApiCreditsSettleRequest(
            negotiation_id=identifier, buyer_principal=BUYER.identity
        )
        pending = await controller._settle_payment(identifier, request, SELLER)
        assert pending.status_code == 202
        with sqlite3.connect(Path(authority) / "authority.db") as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM credit_grants WHERE obligation_ref = ?",
                    (identifier,),
                ).fetchone()[0]
                == 0
            )
        print("API credits: before approval -> retryable pending; grants=0", flush=True)
        checked = check(mandate, wire, policy)
        with PaymentsClient(URL, development_account=PAYER) as buyer:
            receipt = buyer.approve(checked, agreement=wire)
            snapshot = buyer.poll(transaction_id(checked), timeout=10, interval=0.01)
            assert verify_receipt(
                receipt, settings.service_identity, mandate=checked, agreement_json=wire
            )
            assert snapshot.snapshot.receipt is not None
    controller = SettleController(db=db, settlement_coordinator=None)
    request = ApiCreditsSettleRequest(
        negotiation_id=identifier, buyer_principal=BUYER.identity
    )
    response = await controller._settle_payment(identifier, request, SELLER)
    final = json.loads(response.body)
    assert final["status"] == "ready", final.get("reason")
    credentials = final["tenant_credentials"]
    assert credentials["balance"] == 10 and credentials["secret"]
    repeated = json.loads(
        (await controller._settle_payment(identifier, request, SELLER)).body
    )
    assert repeated == final
    with sqlite3.connect(Path(authority) / "authority.db") as connection:
        grants = connection.execute(
            "SELECT COUNT(*), SUM(quantity) FROM credit_grants WHERE obligation_ref = ?",
            (identifier,),
        ).fetchone()
        assert grants == (1, 10), grants
    print(
        "API credits: restarted -> ready with private credentials; repeated settle -> ready; grants=1, balance=10"
    )
    payments_client.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
