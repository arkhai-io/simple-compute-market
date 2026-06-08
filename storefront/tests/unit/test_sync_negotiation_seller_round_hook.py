from __future__ import annotations

from datetime import datetime

import pytest

from market_policy.negotiation_middleware import NegotiationDecision
from market_policy.negotiation_thread import get_thread_store
from market_policy.identity import Identity
from market_storefront.utils.sync_negotiation import (
    SellerRoundResult,
    continue_sync_negotiation,
    start_sync_negotiation,
)
from service.schemas import EscrowProposal, ProvisionTerms


_BUYER = "0xBuyer00000000000000000000000000000000AB"
_TOKEN = "0x0000000000000000000000000000000000000001"
_ESCROW = "0x" + "11" * 20


@pytest.fixture
async def db(tmp_path):
    import market_policy.negotiation_thread as thread_module
    from market_storefront.utils.sqlite_client import SQLiteClient

    client = SQLiteClient(db_path=str(tmp_path / "seller_round_hook.db"))
    thread_module._thread_store = None
    get_thread_store(
        sqlite_client=client,
        identity=Identity(agent_url="http://test-seller:8001"),
    )
    await client.upsert_listing(
        listing_id="L-hook",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
        },
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": _ESCROW,
            "literal_fields": {"token": _TOKEN},
            "rates": [{"field": "amount", "per": "hour", "value": "100"}],
        }],
        fulfillment_resource=None,
        max_duration_seconds=7200,
        seller="http://seller:8001",
    )
    return client


def _proposal(amount: int) -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": amount},
        literal_fields={"token": _TOKEN},
        rates=[{"field": "amount", "per": "hour", "value": "100"}],
        expiration_unix=1_800_000_000,
    )


@pytest.mark.asyncio
async def test_start_sync_negotiation_uses_injected_seller_round_hook(db):
    seen = {}

    async def hook(**kwargs):
        seen["history"] = kwargs["history"]
        seen["has_policy_inputs"] = "policy_inputs" in kwargs
        seen["has_sqlite_client"] = "sqlite_client" in kwargs
        return SellerRoundResult(
            our_amount=123,
            strategy_label="maximize",
            direction="maximize",
            chain_label="custom",
            decision=NegotiationDecision(
                action="counter",
                proposal=_proposal(123).model_dump(),
            ),
        )

    response = await start_sync_negotiation(
        sqlite_client=db,
        our_listing_id="L-hook",
        buyer_address=_BUYER,
        proposal=_proposal(50),
        provision_terms=ProvisionTerms(duration_seconds=3600, ssh_public_key="ssh-rsa AAAA"),
        our_base_url="http://test-seller:8001",
        their_agent_url="http://buyer:9000",
        seller_round_hook=hook,
    )

    assert response["action"] == "counter"
    assert response["proposal"]["fields"]["amount"] == 123
    assert seen["history"][0].proposal["fields"]["amount"] == 50
    assert seen["has_policy_inputs"] is False
    assert seen["has_sqlite_client"] is False


@pytest.mark.asyncio
async def test_continue_sync_negotiation_uses_injected_seller_round_hook(db):
    async def opening_hook(**_kwargs):
        return SellerRoundResult(
            our_amount=100,
            strategy_label="maximize",
            direction="maximize",
            chain_label="custom",
            decision=NegotiationDecision(
                action="counter",
                proposal=_proposal(100).model_dump(),
            ),
        )

    opened = await start_sync_negotiation(
        sqlite_client=db,
        our_listing_id="L-hook",
        buyer_address=_BUYER,
        proposal=_proposal(50),
        provision_terms=ProvisionTerms(duration_seconds=3600, ssh_public_key="ssh-rsa AAAA"),
        our_base_url="http://test-seller:8001",
        their_agent_url="http://buyer:9000",
        seller_round_hook=opening_hook,
    )

    seen = {}

    async def continue_hook(**kwargs):
        seen["history"] = kwargs["history"]
        seen["has_policy_inputs"] = "policy_inputs" in kwargs
        seen["has_sqlite_client"] = "sqlite_client" in kwargs
        return SellerRoundResult(
            our_amount=100,
            strategy_label="maximize",
            direction="maximize",
            chain_label="custom",
            decision=NegotiationDecision(
                action="accept",
                proposal=_proposal(100).model_dump(),
                reason="custom",
            ),
        )

    response = await continue_sync_negotiation(
        sqlite_client=db,
        neg_id=opened["negotiation_id"],
        buyer_action="counter",
        buyer_proposal=_proposal(100).model_dump(),
        buyer_reason=None,
        buyer_address=_BUYER,
        seller_round_hook=continue_hook,
    )

    assert response["action"] == "accept"
    assert response["accepted_escrow_proposal"]["fields"]["amount"] == 100
    assert seen["history"][-1].sender == "them"
    assert seen["history"][-1].proposal["fields"]["amount"] == 100
    assert seen["has_policy_inputs"] is False
    assert seen["has_sqlite_client"] is False
