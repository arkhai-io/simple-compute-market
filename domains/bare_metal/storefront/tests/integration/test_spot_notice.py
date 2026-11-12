"""Lane-only approved rate commands through the composed bare-metal application."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from arkhai_bare_metal_buyer.config import BareMetalBuyerConfig
from arkhai_bare_metal_buyer.lifecycle import buyer_lifecycle
from arkhai_bare_metal_storefront.lifecycle_records import register_agreement
from market_arkhai_payments import PaymentApproval, PaymentSettlementData, derive_mandate, mandate_policy_for_agreement, transaction_id
from market_core.schemas import derive_settlement_option_id
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_deal_lifecycle_client import SellerLifecycleClient
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClient

from integration.test_payment_settlement_client import (
    ADMIN, BUYER, SELLER, PAYER, SERVICE, harness, enabled,
)


@pytest.mark.asyncio
async def test_bare_metal_seller_notice_and_normal_buyer_end_use_the_rate_authority(harness, tmp_path):
    h = harness
    lifecycle = h.runtime.lifecycle
    accepted, _ = lifecycle.agreement(h.negotiation_id)
    raw = accepted.model_dump(mode="json", exclude_none=True)
    now = lifecycle.clock()
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    raw.update(start_utc=stamp, accepted_at=stamp, duration_seconds=3600)
    option = raw["settlement"]
    option["settlement"].update(period="PT60S", reserve_ahead_seconds=120, approval_window="PT60S")
    option["price"]["rates"] = [{"field": "amount", "per": "hour", "value": 6000}]
    option["lifecycle"]["delivery_deadline_seconds"] = 30
    option["lifecycle"]["early_termination"] = {
        "version": 1, "entitlements": {
            "payer": {"notice_seconds": 300, "settles_through": "started_period"},
            "payee": {"notice_seconds": 600, "settles_through": "started_period"},
        }, "settles_through": "started_period",
    }
    option["option_id"] = derive_settlement_option_id(**{k: v for k, v in option.items() if k != "option_id"})
    config = h.runtime.settlement_composition.arkhai_payments_stage().config
    mandate = derive_mandate(raw, mandate_policy_for_agreement(raw, config))
    data = PaymentSettlementData(mandate=mandate, transaction_id=transaction_id(mandate))
    h.payments.signer, h.payments.observed_at = SERVICE, now
    h.payments.engine.fund(PAYER, "USD/2", 1_000_000)
    h.payments.receipt = h.payments.engine.approve(mandate, account=PAYER)
    with transaction(lifecycle.path) as conn:
        # Replace only uncommitted fixture preconditions; no rate option is
        # published or delivered through the installed composition.
        conn.execute("DELETE FROM servicing_seller_deals WHERE negotiation_id=?", (h.negotiation_id,))
        conn.execute("DELETE FROM servicing_delivery WHERE negotiation_id=?", (h.negotiation_id,))
        conn.execute("UPDATE negotiation_threads SET agreement_bytes=?,settlement_data=? WHERE negotiation_id=?",
                     (json.dumps(raw).encode(), json.dumps(data.to_wire()), h.negotiation_id))
        register_agreement(conn, json.dumps(raw).encode(), data.to_wire())
        EndSession(conn).confirm_commitment(h.negotiation_id, committed_at=now)
    transport = httpx.ASGITransport(app=h.app)
    trust = TrustedIdentitySet(identities=(SELLER.identity,))
    async with StorefrontClient("http://test", signer=ADMIN, caller_role="admin",
                                expected_publishers=trust, transport=transport) as admin:
        seller = SellerLifecycleClient(admin)
        assert (await seller.notice(h.negotiation_id, operation_key="seller")).outcome.status == "accepted"
        assert (await seller.read(h.negotiation_id)).authority.parts[0].pending_stop.at == now + 600
        assert (await seller.list()).deals[0].parts[0].pending_stop.at == now + 600
    buyer_config = BareMetalBuyerConfig(
        registry_url="http://registry.example", registry_authority="fixture", registry_principals=(SELLER.identity,),
    )
    async with buyer_lifecycle(
        agreement_bytes=json.dumps(raw).encode(), settlement_data=data.to_wire(), seller_url="http://test",
        signer=BUYER, publishers=trust, config=buyer_config,
        approval=PaymentApproval(config, PAYER, client_for_owner=h.payments),
        store=FileEvidenceStore(tmp_path / "buyer"), transport=transport,
    ) as buyer:
        progress = await buyer.end(h.negotiation_id)
        assert progress.mode == "normal_stop" and progress.payment.status == progress.hint.status == "accepted"
        assert progress.payment.records[0].at == now + 300 and progress.acknowledgement is None
        assert (await buyer.read(h.negotiation_id)).authority.parts[0].pending_stop.at == now + 300
    with transaction(lifecycle.path) as conn:
        assert EndSession(conn).requests(h.negotiation_id) == []
    h.payments.observed_at = now + 300
    async for _ in lifecycle.seller.watch(h.negotiation_id):
        pass
    with transaction(lifecycle.path) as conn:
        assert EndSession(conn).selected_end(h.negotiation_id).ended_at == now + 300
        assert not [item for item in EndSession(conn).intents(h.negotiation_id) if item.kind == "filing"]
