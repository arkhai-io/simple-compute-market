from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_capacity_publication import CapacityBinding
from market_identity import Ed25519Signer

from market_storefront.failure_actions import (
    FulfillmentFailureContext,
    apply_fulfillment_failure_policy,
)
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient

BUYER_PRINCIPAL = Ed25519Signer(b"\x51" * 32).identity
BUYER_EVM_ADDRESS = "0x" + "bb" * 20


@pytest.mark.asyncio
async def test_failure_policy_releases_capacity_and_runs_webhook(tmp_path, monkeypatch):
    from tests.fake_site import FakeSite, capacity_runtime_over

    db = SQLiteClient(db_path=str(tmp_path / "failure-policy.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(
        "gpu-host-1",
        2,
        attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "kvm1"},
    )
    binding = CapacityBinding("site-test", "vm", "pool-test")
    capacity = capacity_runtime_over(fake, site_name=binding.site_id)

    async def resolve_capacity_binding(repository, listing_id):
        assert repository is db
        assert listing_id == "listing-1x"
        return binding

    monkeypatch.setattr(
        "market_storefront.services.capacity_client.capacity_binding_for_listing",
        resolve_capacity_binding,
    )

    async def fake_webhook(payload):
        assert payload["capacity_reservation_id"] == reserved["capacity_reservation_id"]
        assert payload["reason"] == "provisioning_error"
        assert payload["state"] == "released"
        return {"action": "webhook", "status": "sent", "status_code": 204}

    monkeypatch.setattr(
        "market_storefront.failure_actions._configured_failure_actions_source",
        lambda: ["release_capacity", "webhook"],
    )
    webhook = AsyncMock(side_effect=fake_webhook)
    monkeypatch.setattr("market_storefront.failure_actions._send_webhook", webhook)

    reserved = await capacity.reserve(
        binding,
        claim={
            "executor_kind": "vm",
            "resource_id": "gpu-host-1",
            "gpu_count": 1,
        },
        deal_ref={"listing_id": "listing-1x", "escrow_uid": "escrow-1"},
    )
    assert reserved is not None

    result = await apply_fulfillment_failure_policy(
        db,
        FulfillmentFailureContext(
            listing_id="listing-1x",
            capacity_reservation_id=reserved["capacity_reservation_id"],
            escrow_uid="escrow-1",
            reason="provisioning_error",
            message="host rejected request",
            source="test",
        ),
        capacity=capacity,
    )

    assert result.state == "released"
    assert result.resource_id == "gpu-host-1"
    assert result.actions == [
        {"action": "release_capacity", "status": "ok"},
        {"action": "webhook", "status": "sent", "status_code": 204},
    ]
    webhook.assert_awaited_once()

    # The ledger holds the failure metadata; the capacity came back.
    reservation = fake.reservations[reserved["capacity_reservation_id"]]
    assert reservation["state"] == "released"
    assert reservation["failure_reason"] == "provisioning_error"
    assert fake._available("gpu-host-1") == 2


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
                "buyer_principal": BUYER_PRINCIPAL.model_dump(mode="json"),
                "buyer_evm_address": BUYER_EVM_ADDRESS,
                "seller_principal": Ed25519Signer(b"\x52" * 32).identity.model_dump(
                    mode="json"
                ),
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
        kind="erc20_escrow_obligation_default",
        refund_claimed=AsyncMock(return_value={"tx_hash": "0xrefund"}),
    )
    fake_terms = SimpleNamespace(
        obligation_data={"token": "0x" + "cc" * 20, "amount": 42}
    )

    monkeypatch.setattr(
        "market_storefront.failure_actions._configured_failure_actions_source",
        lambda: ["refund"],
    )
    monkeypatch.setattr(
        "market_storefront.failure_actions.get_evm_wallet_private_key",
        lambda: "seller-pk",
    )
    monkeypatch.setattr(
        "market_storefront.failure_actions.get_evm_wallet_address",
        lambda: "0x" + "dd" * 20,
    )
    monkeypatch.setattr(
        "market_storefront.failure_actions.stage_event",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "market_storefront.utils.config.CHAINS",
        {
            "anvil": SimpleNamespace(
                rpc_url="http://rpc", alkahest_address_config_path="/addr.json"
            )
        },
    )
    monkeypatch.setattr(
        "market_alkahest.alkahest.materialize_escrow_terms_from_proposal",
        lambda **kwargs: [fake_terms],
    )
    monkeypatch.setattr(
        "market_alkahest.alkahest.get_escrow_codec_for",
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
            "escrow_kind": "erc20_escrow_obligation_default",
            "body": {"tx_hash": "0xrefund"},
        }
    ]
    fake_codec.refund_claimed.assert_awaited_once_with(
        private_key="seller-pk",
        rpc_url="http://rpc",
        obligation_data={"token": "0x" + "cc" * 20, "amount": 42},
        to_address=BUYER_EVM_ADDRESS,
    )
    assert db.listing_updates == [{"listing_id": "listing-1", "status": "refunded"}]
    assert db.escrow_updates == [{"escrow_uid": "escrow-1", "status": "refunded"}]
