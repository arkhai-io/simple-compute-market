from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_capacity_publication import PublicationBinding
from market_resource_pools_contracts.backing import BACKED
from market_identity import Ed25519Signer

from market_storefront.failure_actions import (
    FulfillmentFailureContext,
    apply_fulfillment_failure_policy,
)
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import FakeProjectionSite, site_projection_state

BUYER_PRINCIPAL = Ed25519Signer(b"\x51" * 32).identity
BUYER_EVM_ADDRESS = "0x" + "bb" * 20


@pytest.mark.asyncio
@pytest.mark.parametrize("projections", ["held", "absent", "another_site"])
async def test_failure_policy_releases_capacity_and_runs_webhook(
    tmp_path, monkeypatch, projections
):
    """The site's release is recorded whatever the projection state can do
    after it: the held site is refreshed before the reopen, and a state that is
    absent or does not hold the site fails nothing."""
    from tests.fake_site import FakeSite, capacity_runtime_over

    db = SQLiteClient(db_path=str(tmp_path / "failure-policy.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(
        "gpu-host-1",
        2,
        attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "kvm1"},
    )
    binding = PublicationBinding("site-test", "vm", "pool-test", BACKED)
    capacity = capacity_runtime_over(fake, site_name=binding.site_id)
    site_projections = {
        # The state over the runtime's own aggregate, as the root composes it.
        "held": site_projection_state(capacity.client()),
        "absent": None,
        "another_site": site_projection_state(
            {"elsewhere": FakeProjectionSite(resource_pools=[])}
        ),
    }[projections]

    async def resolve_capacity_binding(repository, listing_id):
        assert repository is db
        assert listing_id == "listing-1x"
        return binding

    monkeypatch.setattr(
        "market_storefront.failure_actions.capacity_binding_for_listing",
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
            "offering_mode": "vm",
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
        site_projections=site_projections,
    )

    assert result.state == "released"
    assert result.capacity_reservation_id == reserved["capacity_reservation_id"]
    assert result.resource_id == "gpu-host-1"
    assert result.reopened_listing_ids == []
    # Only a state holding the site refreshes it before the reopen.
    refreshed = ("GET", "/api/v1/capacity/site-resource-pools") in fake.requests
    assert refreshed is (projections == "held")
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


_ACCEPTED_ESCROW_PROPOSAL = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "aa" * 20,
    "fields": {"token": "0x" + "cc" * 20},
    "expiration_unix": 1_800_000_000,
}
_ACCEPTED_OBLIGATION_DATA = {
    "arbiter": "0x" + "bb" * 20,
    "demand": "0x" + "dd" * 32,
    "token": "0x" + "cc" * 20,
    "amount": "42",
}


def _accepted_plan(escrow_contract: str = "0x" + "aa" * 20) -> dict:
    """The accepted plan as the thread row returns it, decoded from its JSON."""
    return {
        "obligations": [
            {
                "payer": "buyer",
                "claimant": "seller",
                "amount": "42",
                "asset": "0x" + "cc" * 20,
                "expiration_unix": 1_800_000_000,
                "mechanism": "alkahest.v1",
                "params": {
                    "chain_name": "anvil",
                    "escrow_contract": escrow_contract,
                    "obligation_data": dict(_ACCEPTED_OBLIGATION_DATA),
                },
            }
        ],
        "service_terms": {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recorded",
    [
        pytest.param(
            {
                "settlement_data": {"accepted_escrow_proposal": _ACCEPTED_ESCROW_PROPOSAL},
                "buyer_escrow_proposal": _ACCEPTED_ESCROW_PROPOSAL,
                "settlement_plan": _accepted_plan(),
            },
            id="accepted proposal recorded",
        ),
        pytest.param(
            {
                "settlement_data": {"accepted_escrow_proposal": _ACCEPTED_ESCROW_PROPOSAL},
                "buyer_escrow_proposal": _ACCEPTED_ESCROW_PROPOSAL,
                "settlement_plan": _accepted_plan("0x" + "ee" * 20),
            },
            id="accepted plan names another escrow",
        ),
        pytest.param(
            {"buyer_escrow_proposal": _ACCEPTED_ESCROW_PROPOSAL},
            id="buyer's opening only",
        ),
    ],
)
async def test_failure_policy_refund_uses_escrow_codec_for_proposal(monkeypatch, recorded):
    """A refund returns the token and amount of the accepted plan's obligation
    on the escrow, read as accepted rather than materialized again, and only
    for a deal that recorded its accepted escrow proposal, never the buyer's
    opening alone."""

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
                **recorded,
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

    monkeypatch.setattr(
        "market_storefront.failure_actions._configured_failure_actions_source",
        lambda: ["refund"],
    )
    monkeypatch.setattr(
        "market_storefront.failure_actions.get_evm_wallet_private_key",
        lambda: "seller-pk",
    )
    monkeypatch.setattr(
        "market_storefront.failure_actions.stage_event",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "market_storefront.utils.config.CHAINS",
        {"anvil": SimpleNamespace(rpc_url="http://rpc")},
    )
    monkeypatch.setattr(
        "market_storefront.failure_actions.get_escrow_codec_for",
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

    if "settlement_data" not in recorded:
        assert result.actions == [
            {
                "action": "refund",
                "status": "failed",
                "reason": "accepted_escrow_proposal_unavailable",
            }
        ]
        fake_codec.refund_claimed.assert_not_awaited()
        assert db.escrow_updates == []
        return
    if recorded["settlement_plan"] != _accepted_plan():
        (action,) = result.actions
        assert (action["status"], action["reason"]) == (
            "failed",
            "escrow_refund_context_invalid",
        )
        fake_codec.refund_claimed.assert_not_awaited()
        assert db.escrow_updates == []
        return
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
        obligation_data={**_ACCEPTED_OBLIGATION_DATA, "amount": 42},
        to_address=BUYER_EVM_ADDRESS,
    )
    assert db.listing_updates == [{"listing_id": "listing-1", "status": "refunded"}]
    assert db.escrow_updates == [{"escrow_uid": "escrow-1", "status": "refunded"}]
