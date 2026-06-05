from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from market_storefront.utils.failure_policy import (
    FulfillmentFailureContext,
    apply_fulfillment_failure_policy,
)
from market_storefront.utils.sqlite_client import SQLiteClient


@pytest.mark.asyncio
async def test_failure_policy_releases_capacity_and_runs_webhook(tmp_path, monkeypatch):
    db = SQLiteClient(db_path=str(tmp_path / "failure-policy.db"))
    await db.upsert_resource(
        resource_id="gpu-host-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=2,
        state="available",
        attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "kvm1"},
    )
    reserved = await db.reserve_available_compute_vm(
        required_attributes={"resource_id": "gpu-host-1", "gpu_count": 1},
        listing_id="listing-1x",
        escrow_uid="escrow-1",
    )
    assert reserved is not None

    async def fake_webhook(payload):
        assert payload["allocation_id"] == reserved["allocation_id"]
        assert payload["reason"] == "provisioning_error"
        assert payload["state"] == "released"
        return {"action": "webhook", "status": "sent", "status_code": 204}

    monkeypatch.setattr(
        "market_storefront.utils.failure_policy.configured_failure_actions",
        lambda: ["release_capacity", "webhook"],
    )
    webhook = AsyncMock(side_effect=fake_webhook)
    monkeypatch.setattr("market_storefront.utils.failure_policy._send_webhook", webhook)

    result = await apply_fulfillment_failure_policy(
        db,
        FulfillmentFailureContext(
            allocation_id=reserved["allocation_id"],
            escrow_uid="escrow-1",
            reason="provisioning_error",
            message="host rejected request",
            source="test",
        ),
    )

    assert result.state == "released"
    assert result.resource_id == "gpu-host-1"
    assert result.actions == [
        {"action": "release_capacity", "status": "ok"},
        {"action": "webhook", "status": "sent", "status_code": 204},
    ]
    webhook.assert_awaited_once()

    allocation = await db.update_compute_allocation_state(
        allocation_id=reserved["allocation_id"],
        state="released",
    )
    assert allocation is not None
    assert allocation["state"] == "released"


@pytest.mark.asyncio
async def test_failure_policy_refund_uses_escrow_codec_for_proposal(monkeypatch):
    class FakeDb:
        def __init__(self):
            self.listing_updates = []
            self.escrow_updates = []

        async def load_escrow(self, *, escrow_uid):
            return {
                "escrow_uid": escrow_uid,
                "negotiation_id": "neg-1",
                "chain_name": "anvil",
                "escrow_address": "0x" + "aa" * 20,
            }

        async def load_negotiation_thread_row(self, *, negotiation_id):
            return {
                "negotiation_id": negotiation_id,
                "buyer": "0x" + "bb" * 20,
                "buyer_escrow_proposal": {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "aa" * 20,
                    "fields": {"token": "0x" + "cc" * 20},
                    "expiration_unix": 1_800_000_000,
                },
                "agreed_price": 42,
                "agreed_duration_seconds": 3600,
            }

        async def update_listing(self, **kwargs):
            self.listing_updates.append(kwargs)

        async def update_escrow(self, **kwargs):
            self.escrow_updates.append(kwargs)

    fake_codec = SimpleNamespace(
        kind="erc20_escrow_obligation_nontierable",
        refund_claimed=AsyncMock(return_value={"tx_hash": "0xrefund"}),
    )
    fake_terms = SimpleNamespace(
        obligation_data={"token": "0x" + "cc" * 20, "amount": 42}
    )

    monkeypatch.setattr(
        "market_storefront.utils.failure_policy.configured_failure_actions",
        lambda: ["refund"],
    )
    monkeypatch.setattr(
        "market_storefront.utils.failure_policy.settings",
        SimpleNamespace(wallet=SimpleNamespace(private_key="seller-pk", address="0xseller")),
    )
    monkeypatch.setattr(
        "market_storefront.utils.failure_policy.stage_event",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "market_storefront.utils.config.CHAINS",
        {"anvil": SimpleNamespace(rpc_url="http://rpc", alkahest_address_config_path="/addr.json")},
    )
    monkeypatch.setattr(
        "service.clients.alkahest.materialize_escrow_terms_from_proposal",
        lambda **kwargs: [fake_terms],
    )
    monkeypatch.setattr(
        "service.clients.alkahest.get_escrow_codec_for",
        lambda *args, **kwargs: fake_codec,
    )

    db = FakeDb()
    result = await apply_fulfillment_failure_policy(
        db,
        FulfillmentFailureContext(
            listing_id="listing-1",
            escrow_uid="escrow-1",
            reason="provisioning_error",
        ),
    )

    assert result.actions == [
        {
            "action": "refund",
            "status": "refunded",
            "escrow_kind": "erc20_escrow_obligation_nontierable",
            "body": {"tx_hash": "0xrefund"},
        }
    ]
    fake_codec.refund_claimed.assert_awaited_once_with(
        private_key="seller-pk",
        rpc_url="http://rpc",
        obligation_data={"token": "0x" + "cc" * 20, "amount": 42},
        to_address="0x" + "bb" * 20,
    )
    assert db.listing_updates == [{"listing_id": "listing-1", "status": "refunded"}]
    assert db.escrow_updates == [{"escrow_uid": "escrow-1", "status": "refunded"}]
