"""Real payment ledger and HTTP credit authority; storefront restart and grant replay."""

import asyncio
import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
from apicredits_storefront import container
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.services.payment_settlement_service import (
    ApiCreditPaymentSettlementService,
)
from apicredits_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from apicredits_storefront.utils.sqlite_client import SQLiteClient
from market_arkhai_payments import PaymentApproval, PaymentSellerStage
from market_core import ImmutableFulfillmentCapability
from market_settlement_runtime import compile_settlement_publication_clause
from smoke_common import (
    BUYER,
    DISPUTE,
    PAYEE,
    PAYER,
    SELLER,
    URL,
    agreement,
    config,
    crash,
)

from arkhai_apicredits.listings.models import coerce_resource_dict
from arkhai_apicredits.settlement.credits_client import CreditsServiceClient
from arkhai_apicredits.settlement.fulfillment import fulfill_api_credits_obligation
from arkhai_apicredits.settlement.payments import validate_payment_publication_clause


async def check_configuration():
    """Exercise shared payment readiness and credit publication without services."""
    registry = build_storefront_settlement_registry()
    settings = registry.resolve(
        {
            "schema_version": 1,
            "priority": ["arkhai.payments.v1"],
            "arkhai_payments": {
                "enabled": True,
                "service_url": URL,
                "service_identity": SELLER.identity.model_dump(mode="json"),
                "fee_bps": 250,
                "dispute_authority": DISPUTE,
                "development_auth": True,
            },
        },
        role="seller",
    )
    readiness = await registry.ordered_readiness(settings, role="seller", resources={})
    payment_ready = next(
        status for status in readiness if status.mechanism == "arkhai.payments.v1"
    )
    assert payment_ready.ready
    clause = compile_settlement_publication_clause(
        "mechanism=arkhai.payments.v1 asset=USD/2 rate=125/credit "
        f"arkhai_payments.payee_account={PAYEE} arkhai_payments.asset=USD/2 "
        "arkhai_payments.window=P7D arkhai_payments.deposit_agreement=true",
        registry=registry,
        config=settings,
        role="seller",
    )
    validate_payment_publication_clause(clause)
    artifacts = registry.build_option(
        payment_ready, settings, role="seller", resources={"publication_clause": clause}
    )
    assert artifacts["accepted_escrows"] == []
    assert artifacts["settlement_options"][0]["rates"] == [
        {"field": "amount", "per": "credit", "value": "125"}
    ]
    print(
        "API credits: shared config ready; payment option=125 base units/credit; no wallet, chain or service calls"
    )


async def main(directory, phase, authority):
    settings = config()
    response = httpx.get("http://127.0.0.1:3181/health", trust_env=False)
    response.raise_for_status()
    db = SQLiteClient(str(Path(directory) / "storefront.db"))
    identifier = "api-smoke-" + Path(directory).name

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
    composition = SimpleNamespace(domain=domain)
    container.resolved_settlement_composition = composition
    stage = PaymentSellerStage(settings)
    service = ApiCreditPaymentSettlementService(db=db, composition=composition, stage=stage)

    async def settle():
        return await service.settle(
            identifier, buyer_principal=BUYER.identity, seller_principal=SELLER.identity
        )
    if phase == "crash":
        provision = {
            "kind": "api_credits.v1",
            "schema_version": 1,
            "payload": {"quantity": 10, "key_mode": "new"},
        }
        accepted = agreement(identifier, provision, duration=0)
        raw = accepted.model_dump_json(exclude_none=True).encode()
        settlement_data = stage.settlement_data(json.loads(raw)).to_wire()
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
            settlement_data=settlement_data,
        )
        await db.save_credit_terms(
            negotiation_id=identifier, quantity=10, key_mode="new"
        )
        await db.update_negotiation_thread_terminal(
            negotiation_id=identifier, terminal_state="success"
        )
        pending = await settle()
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
        PaymentApproval(settings, PAYER).approve(
            raw, settlement_data, timeout=10, interval=0.01
        )
    response = await settle()
    final = response.payload
    assert final["status"] == "ready", final.get("reason")
    credentials = final["tenant_credentials"]
    assert credentials["balance"] == 10 and credentials["secret"]
    repeated = (await settle()).payload
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


if __name__ == "__main__":
    if sys.argv[1:] == ["--check-config"]:
        asyncio.run(check_configuration())
    else:
        asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
