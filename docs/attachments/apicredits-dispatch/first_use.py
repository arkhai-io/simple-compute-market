"""Controlled payment-stage recovery through the real typed credits HTTP app.

No payment ledger is represented here: the payments I/O boundary supplies a
synthetically signed receipt, verified by the installed payments kit. The
credits app, quota ledger, storefront repositories and issuance client are real.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from market_identity import Ed25519Signer, SignatureProof
from market_identity.canonical import _frame
from market_arkhai_payments import (
    PaymentsPollTimeout, SignedReceipt, derive_mandate, transaction_id,
)
from market_arkhai_payments.canonical import jcs_sha256
from market_arkhai_payments.receipts import RECEIPT_PROTOCOL
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id

from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.settlement_composition import SELLER_STAGES, build_storefront_settlement_registry
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest
from apicredits_storefront.settlement_stages import project_progress
from apicredits_storefront.utils.sqlite_client import SQLiteClient
from domains.apicredits.negotiation.terms import make_api_credits_provision_terms
from domains.apicredits.settlement import mandate_policy_from_agreement
from domains.apicredits.settlement.credits_client import CreditsServiceClient
from domains.apicredits.settlement.fulfillment import fulfill_api_credits_obligation

BUYER = Ed25519Signer(bytes.fromhex("11" * 32))
SELLER = Ed25519Signer(bytes.fromhex("22" * 32))
RECEIPT_SIGNER = Ed25519Signer(bytes.fromhex("55" * 32))
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"


class PaymentBoundary:
    def __init__(self) -> None:
        self.ready = False
        self.receipt = None
        self.polls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def poll(self, reference, **_kwargs):
        self.polls += 1
        if not self.ready:
            raise PaymentsPollTimeout(reference)
        return SimpleNamespace(snapshot=SimpleNamespace(receipt=self.receipt))

    def ensure_agreement_attached(self, *_args):
        pass

    def reverse(self, *_args):
        raise AssertionError("successful issuance must not reverse settlement")


class LostAcknowledgementClient(CreditsServiceClient):
    lose_once = True

    async def submit_credit_issuance(self, request, **kwargs):
        result = await super().submit_credit_issuance(request, **kwargs)
        if self.lose_once:
            self.lose_once = False
            raise TimeoutError("controlled acknowledgement loss after authority commit")
        return result


async def drive(root: Path) -> dict:
    os.environ["APICREDITS_DATABASE_URL"] = "sqlite:///" + str(root / "credits.db")
    os.environ["APICREDITS_STOREFRONT_ADMIN_KEY"] = secrets.token_hex(24)
    os.environ["APICREDITS_STOREFRONT_ADMIN_KEY_FILE"] = ""
    import container as authority
    from main import app

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://credits.local") as health:
            response = await health.get("/health")
            response.raise_for_status()
        authority.resolved_capacity_ledger_service.register_resource(
            resource_id="svc-quota", total_units=100, resource_type="api_credits",
        )
        db = SQLiteClient(str(root / "storefront.db"))
        client = LostAcknowledgementClient(
            "http://credits.local", os.environ["APICREDITS_STOREFRONT_ADMIN_KEY"],
            transport=httpx.ASGITransport(app=app),
        )
        config = build_storefront_settlement_registry().resolve({
            "schema_version": 1, "priority": ["arkhai.payments.v1"],
            "arkhai_payments": {
                "enabled": True, "service_url": "http://127.0.0.1:3180",
                "service_identity": RECEIPT_SIGNER.identity.model_dump(mode="json"),
                "fee_bps": 0, "dispute_authority": DISPUTE, "development_auth": True,
            },
        }, role="seller")
        stage = SELLER_STAGES["arkhai.payments.v1"]
        composition = SimpleNamespace(
            settlement_config=config, domain=get_market_domain_contract(), credits_client=client,
        )
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        await db.upsert_listing(
            listing_id="listing-controlled", status="open", created_at=now, updated_at=now,
            offer_resource={"service_name": "controlled-api", "resource_id": "svc-quota",
                            "capacity_site_id": "quota", "offering_mode": "api_credits",
                            "base_url": "http://api.local"},
            fulfillment_resource=None, max_duration_seconds=None,
            storefront_url="http://storefront.local", seller_principal=SELLER.identity,
        )
        boundary = PaymentBoundary()

        async def accepted(negotiation_id: str, *, key_id=None):
            terms = make_api_credits_provision_terms(
                quantity=3 if key_id is None else 2, key_mode="new" if key_id is None else "existing", key_id=key_id,
            )
            params = {"payee_account": PAYEE, "asset": "USD/2", "window": "P7D", "deposit_agreement": True}
            option = SettlementOption(
                option_id=derive_settlement_option_id(mechanism="arkhai.payments.v1", asset="USD/2", rates=[], params=params),
                mechanism="arkhai.payments.v1", asset="USD/2", rates=[], params=params,
            )
            agreement = Agreement(
                negotiation_id=negotiation_id, listing_id="listing-controlled", listing_hash="a"*64,
                buyer=BUYER.identity.model_dump(mode="json"), seller=SELLER.identity.model_dump(mode="json"),
                settlement=option, settlement_params={"payer_account": PAYER}, amount=100,
                asset="USD/2", duration_seconds=0, start_utc=now, accepted_at=now,
                provision_terms=terms.model_dump(mode="json"),
            )
            raw = agreement.model_dump_json(exclude_none=True).encode()
            wire = agreement.model_dump(mode="json", exclude_none=True)
            artifacts = stage.agreement_artifacts(wire, config)
            await db.create_negotiation_thread(
                negotiation_id=negotiation_id, our_listing_id="listing-controlled", their_listing_id="",
                our_agent_id="seller", their_agent_id="buyer", owner_id="seller",
                buyer_principal=BUYER.identity, seller_principal=SELLER.identity,
                provision_terms=terms.model_dump(mode="json"),
            )
            await db.commit_agreed_terms(
                negotiation_id=negotiation_id, agreed_price=100, agreed_duration_seconds=0,
                agreement_bytes=raw, accepted_at=now, agreed_start_utc=now, settlement_data=artifacts,
            )
            await db.update_negotiation_thread_terminal(negotiation_id=negotiation_id, terminal_state="success")
            policy = mandate_policy_from_agreement(wire, fee_bps=0, dispute_authority=DISPUTE)
            mandate = derive_mandate(wire, policy).model_dump(mode="json", by_alias=True, exclude_none=True)
            receipt = {
                "transaction": transaction_id(mandate), "deal": mandate["deal"],
                "from": PAYER, "to": PAYEE, "ledger": "controlled-approval",
                "parts": [{"asset": "USD/2", "gross": "100", "fee": "0", "net": "100",
                           "hold": mandate["parts"][0]["hold"]}],
                "approvedAt": int(time.time()), "issuer": RECEIPT_SIGNER.identity.model_dump(mode="json"),
            }
            proof = SignatureProof.from_bytes(
                RECEIPT_SIGNER.identity.scheme,
                RECEIPT_SIGNER.sign(_frame((RECEIPT_PROTOCOL, jcs_sha256(receipt)))),
            )
            boundary.receipt = SignedReceipt.model_validate({"receipt": receipt, "proof": proof.model_dump(mode="json")})
            thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
            return {
                "db": db, "composition": composition, "coordinator": None, "reference": negotiation_id,
                "body": ApiCreditsSettleRequest(negotiation_id=negotiation_id, buyer_principal=BUYER.identity),
                "signer": SELLER, "thread": thread,
            }

        with patch("apicredits_storefront.settlement_stages.payments_client_for_owner", lambda *_args: boundary):
            context = await accepted("neg-controlled-new")
            pending = await stage.settle(**context)
            assert pending["status"] == "provisioning"
            evidence = await db.load_settlement_evidence(negotiation_id="neg-controlled-new")
            try:
                await fulfill_api_credits_obligation(evidence=evidence, credits_client=client, stage_event=lambda *_a, **_k: None)
            except ValueError:
                pass
            else:
                raise AssertionError("pending evidence authorized issuance")
            with sqlite3.connect(root / "credits.db") as conn:
                assert conn.execute("SELECT COUNT(*) FROM credit_grants").fetchone()[0] == 0
            boundary.ready = True
            lost = await stage.settle(**context)
            assert lost["status"] == "provisioning"
            with sqlite3.connect(root / "credits.db") as conn:
                assert conn.execute("SELECT COUNT(*) FROM credit_grants").fetchone()[0] == 1
            # Reopen storefront persistence to exclude worktree-local state.
            context["db"] = db = SQLiteClient(str(root / "storefront.db"))
            ready = await stage.redrive(**context)
            assert ready["status"] == "ready"
            try:
                await project_progress(db, ready, owner=SELLER.identity)
            except PermissionError:
                pass
            else:
                raise AssertionError("private results were exposed to another principal")
            private = await project_progress(db, ready, owner=BUYER.identity)
            key_id = private["tenant_credentials"]["key_id"]
            assert private["tenant_credentials"]["secret"]
            assert "secret" not in json.dumps(ready)
            topup = await stage.settle(**await accepted("neg-controlled-topup", key_id=key_id))
            assert topup["status"] == "ready"
            projected = await project_progress(db, topup, owner=BUYER.identity)
            assert "secret" not in projected["tenant_credentials"]
            await stage.settle(**context)
        with sqlite3.connect(root / "credits.db") as conn:
            grants = conn.execute("SELECT COUNT(*) FROM credit_grants").fetchone()[0]
            balance = conn.execute("SELECT balance FROM api_keys WHERE key_id=?", (key_id,)).fetchone()[0]
        with sqlite3.connect(root / "storefront.db") as conn:
            assert conn.execute("SELECT COUNT(*) FROM escrows").fetchone()[0] == 0
            schema = {table: [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
                      for table in ("api_credit_settlement_evidence", "api_credit_issuance_progress")}
            constraints = {table: conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
                           for table in schema}
        assert grants == 2 and balance == 5
        authority.resolved_session_factory.kw["bind"].dispose()
        return {"readiness": "credits /health=200", "pending_grants": 0, "lost_ack_grants": 1,
                "final_grants": grants, "final_balance": balance, "payment_escrows": 0,
                "source_revalidations": boundary.polls, "schema": schema, "constraints": constraints,
                "qualification": "controlled only; synthetic payment I/O, real credits HTTP app and SQLite"}


async def main():
    with tempfile.TemporaryDirectory(prefix="api-credit-dispatch-") as temporary:
        result = await drive(Path(temporary))
    result["temporary_databases_removed"] = True
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
