"""Sync negotiation through the real API-tokens round hook.

Capacity snapshots and key lookups are faked at the service seams the
default hook resolves at call time; everything else — guards, terminal
policy, thread persistence, token-terms persistence, quota hold — runs
for real against a temp SQLite database.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from apitokens_storefront.utils.sync_negotiation import (
    OfferUnfulfillableError,
    continue_sync_negotiation,
    start_sync_negotiation,
)
from market_core.schemas import EscrowProposal, ProvisionTerms
from market_policy.identity import Identity
from market_policy.negotiation_thread import get_thread_store

_BUYER = "0xBuyerAAAA0000000000000000000000000000ab"
_TOKEN = "0x" + "01" * 20
_ESCROW = "0x" + "11" * 20


class FakeCapacity:
    def __init__(self, available: int = 100) -> None:
        self.available = available
        self.reserved: list[dict] = []

    async def snapshot(self):
        return [{
            "resource_id": "svc-quota",
            "resource_type": "api_tokens",
            "available_units": self.available,
            "total_units": 1000,
            "state": "available",
        }]

    async def reserve(self, *, claim=None, deal_ref=None, ttl_seconds=None):
        self.reserved.append({
            "claim": claim, "deal_ref": deal_ref, "ttl_seconds": ttl_seconds,
        })
        return {
            "allocation_id": f"alloc-{len(self.reserved)}",
            "resource_id": "svc-quota",
            "allocated_units": (claim or {}).get("units"),
            "hold_expires_at": "2099-01-01 00:00",
        }


@pytest.fixture
def fake_capacity(monkeypatch):
    capacity = FakeCapacity()
    from apitokens_storefront.services import capacity_client as cc_module

    monkeypatch.setattr(
        cc_module, "build_capacity_client", lambda factory: capacity,
    )
    return capacity


@pytest.fixture
def key_records(monkeypatch):
    records: dict[str, dict | None] = {}

    async def _lookup(key_id: str):
        return records.get(key_id)

    from apitokens_storefront.services import keys_lookup as kl_module

    monkeypatch.setattr(kl_module, "lookup_key_record", _lookup)
    return records


@pytest.fixture
async def db(tmp_path):
    import market_policy.negotiation_thread as thread_module

    from apitokens_storefront.utils.sqlite_client import SQLiteClient

    client = SQLiteClient(db_path=str(tmp_path / "tokens-storefront.db"))
    thread_module._thread_store = None
    get_thread_store(
        sqlite_client=client,
        identity=Identity(agent_url="http://test-seller:8002"),
    )
    await client.upsert_listing(
        listing_id="L-tok",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "kind": "api_tokens.v1",
            "service_name": "Acme Inference",
            "openapi_url": "https://api.acme.example/openapi.json",
            "base_url": "https://api.acme.example",
            "resource_id": "svc-quota",
        },
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": _ESCROW,
            "literal_fields": {"token": _TOKEN},
            "rates": [{"field": "amount", "per": "token", "value": "100"}],
        }],
        fulfillment_resource=None,
        max_duration_seconds=None,
        seller="http://seller:8002",
    )
    return client


def _proposal(amount: int) -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": amount},
        literal_fields={"token": _TOKEN},
        rates=[{"field": "amount", "per": "token", "value": "100"}],
        expiration_unix=1_800_000_000,
    )


def _terms(quantity=3, key_mode="new", key_id=None) -> ProvisionTerms:
    key: dict = {"mode": key_mode}
    if key_id:
        key["key_id"] = key_id
    return ProvisionTerms(
        kind="api_tokens.v1",
        payload={"quantity": quantity, "key": key},
    )


async def _start(db, *, amount=300, quantity=3, key_mode="new", key_id=None):
    return await start_sync_negotiation(
        sqlite_client=db,
        our_listing_id="L-tok",
        buyer_address=_BUYER,
        proposal=_proposal(amount),
        provision_terms=_terms(quantity, key_mode, key_id),
        our_base_url="http://seller:8002",
        their_agent_url="http://buyer:9000",
    )


async def test_listed_price_accept_persists_terms_and_hold(db, fake_capacity, key_records):
    # quantity 3 × unit rate 100 = 300; opening at the bound accepts
    # under the listed_price default.
    response = await _start(db, amount=300, quantity=3)
    assert response["action"] == "accept"
    assert response["accepted_provision_terms"]["payload"]["quantity"] == 3
    # Plan materialization needs a resolvable alkahest chain config (the
    # e2e topology provides one); here the proposal echo is the artifact.
    assert response["accepted_escrow_proposal"]["fields"]["amount"] == 300

    neg_id = response["negotiation_id"]
    terms = await db.load_token_terms(negotiation_id=neg_id)
    assert terms == {
        "negotiation_id": neg_id, "quantity": 3,
        "key_mode": "new", "key_id": None,
    }

    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == 300

    # Acceptance placed a TTL quota hold with the generic units claim.
    assert fake_capacity.reserved
    hold_req = fake_capacity.reserved[0]
    assert hold_req["claim"] == {"units": 3, "resource_id": "svc-quota"}
    assert hold_req["ttl_seconds"] > 0
    hold = await db.load_capacity_hold(negotiation_id=neg_id)
    assert hold["allocation_id"] == "alloc-1"


async def test_quota_guard_rejects_uncovered_quantity(db, fake_capacity, key_records):
    fake_capacity.available = 2
    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, amount=300, quantity=3)
    assert exc.value.reason.startswith("quota_exhausted")
    assert not fake_capacity.reserved


async def test_existing_key_owned_by_buyer_wallet(db, fake_capacity, key_records):
    key_records["ak_mine"] = {
        "key_id": "ak_mine", "owner_scheme": "wallet",
        "owner_id": _BUYER.upper().replace("0X", "0x"), "status": "active",
    }
    response = await _start(
        db, amount=300, quantity=3, key_mode="existing", key_id="ak_mine",
    )
    assert response["action"] == "accept"
    terms = await db.load_token_terms(
        negotiation_id=response["negotiation_id"],
    )
    assert terms["key_mode"] == "existing"
    assert terms["key_id"] == "ak_mine"


async def test_existing_key_rejections(db, fake_capacity, key_records):
    key_records["ak_theirs"] = {
        "key_id": "ak_theirs", "owner_scheme": "wallet",
        "owner_id": "0x" + "99" * 20, "status": "active",
    }
    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, key_mode="existing", key_id="ak_theirs")
    assert exc.value.reason.startswith("key_not_owned")

    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, key_mode="existing", key_id="ak_missing")
    assert exc.value.reason.startswith("key_not_found")


async def test_open_key_top_up_without_guarded_owner(db, fake_capacity, key_records):
    key_records["ak_open"] = {
        "key_id": "ak_open", "owner_scheme": None,
        "owner_id": None, "status": "active",
    }
    response = await _start(
        db, amount=300, quantity=3, key_mode="existing", key_id="ak_open",
    )
    assert response["action"] == "accept"


async def test_bisection_counter_round_scales_by_quantity(db, fake_capacity, key_records):
    """Counter rounds keep the quantity-scaled reference from the terms row."""
    from tests._settings_overrides import settings_overrides

    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        opening = await _start(db, amount=250, quantity=3)
        assert opening["action"] == "counter"
        neg_id = opening["negotiation_id"]
        countered = int(opening["proposal"]["fields"]["amount"])
        assert countered == 275  # midpoint of 250 and the 300 bound

        response = await continue_sync_negotiation(
            sqlite_client=db,
            neg_id=neg_id,
            buyer_action="accept",
            buyer_proposal=None,
            buyer_reason=None,
            buyer_address=_BUYER,
        )
    assert response["action"] == "accept"
    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == 275


def test_accepted_artifacts_stamp_the_seller_recipient(monkeypatch):
    """The accepted escrow artifacts must carry the seller's wallet as
    the escrow recipient — without it the buyer can't materialize a
    funded escrow ("must carry ... a recipient fallback"). Regression
    guard: the assembly once passed seller_wallet_address=None.
    """
    import apitokens_storefront.utils.sync_negotiation as sn

    captured: dict = {}

    def _fake_artifacts(**kwargs):
        captured.update(kwargs)
        return {"proposal": {}, "accepted_escrow_proposal": {}}

    monkeypatch.setattr(sn, "accepted_escrow_artifacts_from_proposal", _fake_artifacts)
    monkeypatch.setattr(sn, "_seller_wallet_address", lambda: "0xSeLLeR0000")

    sn._accepted_escrow_artifacts(
        proposal={"chain_name": "anvil", "escrow_address": _ESCROW},
        agreed_amount=300,
    )
    assert captured["seller_wallet_address"] == "0xSeLLeR0000"
