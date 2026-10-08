"""Sync negotiation through the real API-credits round hook.

Capacity snapshots and key lookups are faked at the service seams the
default hook resolves at call time; everything else — guards, terminal
policy, thread persistence, token-terms persistence, and the safe default
that grants no unfunded quota hold — runs against a temporary SQLite database.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import (
    _place_quota_hold,
    build_api_credit_negotiation_runtime,
)
from core_storefront.models.negotiation_models import NegotiateNewResponse
from market_negotiation_runtime import OfferUnfulfillableError
from market_identity import Ed25519Signer

from tests.integration.credit_negotiation import (
    BUYER_PRINCIPAL,
    SELLER_PRINCIPAL,
    proposal,
    terms,
)

_STRANGER_PRINCIPAL = Ed25519Signer(bytes.fromhex("33" * 32)).identity
_DOMAIN = get_market_domain_contract()


async def _start(db, *, amount=300, quantity=3, key_mode="new", key_id=None):
    return await build_api_credit_negotiation_runtime(_DOMAIN).start(
        repository=db,
        listing_id="L-tok",
        buyer_principal=BUYER_PRINCIPAL,
        seller_principal=SELLER_PRINCIPAL,
        proposal=proposal(amount),
        terms=terms(quantity, key_mode, key_id),
        seller_agent_url="http://seller:8002",
        buyer_agent_url="http://buyer:9000",
        actor_principal=BUYER_PRINCIPAL,
    )


async def test_listed_price_accept_persists_terms_without_unfunded_hold(
    db, fake_capacity, key_records
):
    # quantity 3 * unit rate 100 = 300; opening at the bound accepts
    # under the listed_price default.
    response = await _start(db, amount=300, quantity=3)
    assert response["action"] == "accept"
    assert response["accepted_provision_terms"]["payload"]["quantity"] == 3
    # Plan materialization needs a resolvable alkahest chain config (the
    # e2e topology provides one); here the proposal echo is the artifact.
    assert response["accepted_escrow_proposal"]["fields"]["amount"] == "300"

    neg_id = response["negotiation_id"]
    terms = await db.load_credit_terms(negotiation_id=neg_id)
    assert terms == {
        "negotiation_id": neg_id,
        "quantity": 3,
        "key_mode": "new",
        "key_id": None,
    }

    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == 300

    assert fake_capacity.reserved == []
    assert await db.load_capacity_hold(negotiation_id=neg_id) is None


async def test_accept_result_satisfies_the_controllers_response_model(
    db, fake_capacity, key_records
):
    """The assertion every test around this one was missing.

    Each of them asserts on the runtime's raw dict, which is the right
    subject for the negotiation logic -- and means none of them noticed
    that the dict could not be loaded into the model the controller has to
    return. `accepted_provision_terms` is typed `ProvisionTerms`, which
    forbids extras, while the credits codec decodes into
    `ApiCreditsMessage`: a superset carrying `settlement_selection`,
    `buyer_principal` and `seller_principal`. Every accepted round 0 was
    therefore a 500, and because the construction sat outside the
    controller's `except`, one with no traceback logged anywhere.

    Constructing the model is the whole assertion. Nothing about the
    values is re-checked here; the tests above own those.
    """
    response = await _start(db, amount=300, quantity=3)
    assert response["action"] == "accept"

    model = NegotiateNewResponse(**response)

    # The narrowing keeps what provision terms are *for*, rather than
    # dropping the field to make the model load.
    assert model.accepted_provision_terms is not None
    assert model.accepted_provision_terms.kind == "api_credits.v1"
    assert model.accepted_provision_terms.payload["quantity"] == 3


async def test_quota_guard_rejects_uncovered_quantity(db, fake_capacity, key_records):
    fake_capacity.available = 2
    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, amount=300, quantity=3)
    assert exc.value.reason.startswith("quota_exhausted")
    assert not fake_capacity.reserved


async def test_existing_key_owned_by_buyer_principal(db, fake_capacity, key_records):
    key_records["ak_mine"] = {
        "key_id": "ak_mine",
        "owner_scheme": BUYER_PRINCIPAL.scheme.value,
        "owner_id": BUYER_PRINCIPAL.identifier,
        "status": "active",
    }
    response = await _start(
        db,
        amount=300,
        quantity=3,
        key_mode="existing",
        key_id="ak_mine",
    )
    assert response["action"] == "accept"
    terms = await db.load_credit_terms(
        negotiation_id=response["negotiation_id"],
    )
    assert terms["key_mode"] == "existing"
    assert terms["key_id"] == "ak_mine"


async def test_existing_key_rejections(db, fake_capacity, key_records):
    key_records["ak_theirs"] = {
        "key_id": "ak_theirs",
        "owner_scheme": _STRANGER_PRINCIPAL.scheme.value,
        "owner_id": _STRANGER_PRINCIPAL.identifier,
        "status": "active",
    }
    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, key_mode="existing", key_id="ak_theirs")
    assert exc.value.reason.startswith("key_not_owned")

    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, key_mode="existing", key_id="ak_missing")
    assert exc.value.reason.startswith("key_not_found")


async def test_open_key_top_up_without_guarded_owner(db, fake_capacity, key_records):
    key_records["ak_open"] = {
        "key_id": "ak_open",
        "owner_scheme": None,
        "owner_id": None,
        "status": "active",
    }
    response = await _start(
        db,
        amount=300,
        quantity=3,
        key_mode="existing",
        key_id="ak_open",
    )
    assert response["action"] == "accept"


async def test_bisection_counter_round_scales_by_quantity(
    db, fake_capacity, key_records
):
    """Counter rounds keep the quantity-scaled reference from the terms row."""
    from tests._settings_overrides import settings_overrides

    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        opening = await _start(db, amount=250, quantity=3)
        assert opening["action"] == "counter"
        neg_id = opening["negotiation_id"]
        countered = int(opening["proposal"]["fields"]["amount"])
        assert countered == 275  # midpoint of 250 and the 300 bound

        response = await build_api_credit_negotiation_runtime(
            _DOMAIN
        ).continue_negotiation(
            repository=db,
            negotiation_id=neg_id,
            buyer_action="accept",
            buyer_proposal=None,
            buyer_reason=None,
            buyer_principal=BUYER_PRINCIPAL,
            seller_principal=SELLER_PRINCIPAL,
            actor_principal=BUYER_PRINCIPAL,
            actor_role="buyer",
        )
    assert response["action"] == "accept"
    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == 275


async def test_force_accept_records_what_a_negotiated_acceptance_records(
    db, fake_capacity, key_records
):
    """Administrative acceptance runs the domain's acceptance hooks: the credit
    terms and agreed price are recorded, and no unfunded quota hold is granted,
    exactly as after a negotiated acceptance."""
    from market_identity import Ed25519Signer
    from tests._settings_overrides import settings_overrides

    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        opening = await _start(db, amount=250, quantity=3)
        assert opening["action"] == "counter"
        neg_id = opening["negotiation_id"]

        response = await build_api_credit_negotiation_runtime(
            _DOMAIN
        ).accept_administratively(
            repository=db,
            listing_id="L-tok",
            negotiation_id=neg_id,
            amount=290,
            actor_principal=Ed25519Signer(b"\x41" * 32).identity,
        )

    assert response["action"] == "accept"
    assert response["amount"] == 290
    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == 290
    assert await db.load_credit_terms(negotiation_id=neg_id) == {
        "negotiation_id": neg_id,
        "quantity": 3,
        "key_mode": "new",
        "key_id": None,
    }
    assert fake_capacity.reserved == []
    assert await db.load_capacity_hold(negotiation_id=neg_id) is None


async def test_payment_selection_places_quota_hold(db, monkeypatch):
    """A payment deal holds its quota between acceptance and the buyer's approval."""
    from apicredits_storefront import negotiation_runtime as runtime_module

    from tests._settings_overrides import settings_overrides

    class CapacityRuntime:
        async def reserve(self, _binding, *, claim, deal_ref, ttl_seconds):
            return {
                "capacity_reservation_id": "alloc-payment",
                "resource_id": "svc-quota",
                "allocated_units": claim["units"],
                "hold_expires_at": "2099-01-01 00:00",
            }

    monkeypatch.setattr(
        runtime_module,
        "build_capacity_runtime",
        lambda _factory: CapacityRuntime(),
    )
    acceptance = SimpleNamespace(
        negotiation_id="neg-payment",
        listing_id="L-tok",
        listing_record={
            "listing_resource": {
                "resource_id": "svc-quota",
                "capacity_site_id": "tokens",
                "offering_mode": "api_credits",
            }
        },
        terms=SimpleNamespace(decoded=SimpleNamespace(payload={"quantity": 3})),
        pinned_proposal=None,
        policy_state={
            "accepted_settlement_selection": {"mechanism": "arkhai.payments.v1"}
        },
        binding=None,
    )

    with settings_overrides(**{"capacity.hold_ttl_seconds": 300}):
        await _place_quota_hold(db, acceptance, {})

    hold = await db.load_capacity_hold(negotiation_id="neg-payment")
    assert hold["capacity_reservation_id"] == "alloc-payment"
    assert hold["payload"]["allocated_units"] == 3
