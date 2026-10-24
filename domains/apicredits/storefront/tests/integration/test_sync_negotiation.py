"""Sync negotiation through the real API-credits round hook.

Capacity snapshots and key lookups are faked at the service seams the
default hook resolves at call time; everything else — guards, terminal
policy, thread persistence, token-terms persistence, and the safe default
that grants no unfunded quota hold — runs against a temporary SQLite database.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from apicredits_storefront import container
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.server import build_api_credit_negotiation_runtime
from apicredits_storefront.settlement_composition import SELLER_STAGES
from arkhai_api_selling.negotiation import place_quota_hold
from core_storefront.models.negotiation_models import NegotiateNewResponse
from market_negotiation_runtime import NegotiationStateError, OfferUnfulfillableError
from market_alkahest.alkahest import encode_recipient_demand
from market_identity import Ed25519Signer
from market_policy.negotiation_middleware import NegotiationDecision
from market_policy.seller_round import SellerRoundResult

from tests._settings_overrides import settings_overrides
from tests.integration.credit_negotiation import (
    BUYER_PRINCIPAL,
    CONDITION,
    FakeCapacity,
    SELLER_PRINCIPAL,
    SELLER_WALLET,
    payment_option,
    payment_selection,
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
    assert response["accepted_escrow_proposal"]["fields"]["amount"] == "300"
    # The chain names the development address book, so the escrow's plan is
    # materialized under the listing's release condition.
    (obligation,) = response["settlement_plan"]["obligations"]
    assert obligation["mechanism"] == "alkahest.v1"
    assert int(obligation["amount"]) == 300
    data = obligation["params"]["obligation_data"]
    assert data["arbiter"].lower() == CONDITION["arbiter"].lower()
    assert data["demand"] == "0x" + encode_recipient_demand(SELLER_WALLET).hex()
    assert obligation["payer_principal"] == BUYER_PRINCIPAL.model_dump(mode="json")
    assert obligation["claimant_principal"] == SELLER_PRINCIPAL.model_dump(mode="json")

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
    assert thread["settlement_plan"] == response["settlement_plan"]

    assert fake_capacity.reserved == []
    assert await db.load_capacity_hold(negotiation_id=neg_id) is None


async def test_an_escrow_whose_plan_cannot_be_materialized_is_refused(
    db, fake_capacity, key_records
):
    """An escrow is accepted only with the plan its settlement is verified
    against: a proposal the codecs cannot price refuses the round under the
    listed-price default, and nothing is recorded."""
    unpriceable = proposal(300).model_copy(
        update={
            "rates": [
                *proposal(300).rates,
                {"field": "bonus", "per": "fortnight", "value": "1"},
            ]
        }
    )

    with pytest.raises(OfferUnfulfillableError, match="settlement_plan_unmaterializable"):
        await build_api_credit_negotiation_runtime(_DOMAIN).start(
            repository=db,
            listing_id="L-tok",
            buyer_principal=BUYER_PRINCIPAL,
            seller_principal=SELLER_PRINCIPAL,
            proposal=unpriceable,
            terms=terms(3),
            seller_agent_url="http://seller:8002",
            buyer_agent_url="http://buyer:9000",
            actor_principal=BUYER_PRINCIPAL,
        )

    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM negotiation_threads").fetchone()[0] == 0


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
    values is re-checked here; the tests above own those. The accepted
    response is proven over the wire, through the buyer's own negotiation
    client against the served routes, in `test_credits_negotiate_cli.py`.
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


async def test_quota_guard_reads_only_the_listings_own_site(db, monkeypatch, key_records):
    """Another site naming the same quota resource cannot cover the quantity."""
    bound = FakeCapacity(available=2)
    other = FakeCapacity(available=100)

    class _TwoSites:
        site_names = ["tokens", "elsewhere"]

        def site(self, site_id):
            return {"tokens": bound, "elsewhere": other}[site_id]

        async def snapshot(self):
            return [
                {**row, "site": name}
                for name, site in (("tokens", bound), ("elsewhere", other))
                for row in await site.snapshot()
            ]

    monkeypatch.setattr(container.QUOTA_CAPACITY, "client", lambda factory: _TwoSites())

    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, amount=300, quantity=3)
    assert exc.value.reason.startswith("quota_exhausted")


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


async def test_an_opened_thread_takes_its_listings_binding(db, fake_capacity, key_records):
    """The thread is bound when it opens, before anything is accepted."""
    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        opening = await _start(db, amount=250, quantity=3)
    assert opening["action"] == "counter"

    thread = await db.load_thread_binding(negotiation_id=opening["negotiation_id"])
    listing = await db.load_listing_binding(listing_id="L-tok")
    assert thread.listing_id == "L-tok"
    assert (thread.site_id, thread.binding) == (listing.site_id, listing.binding)


async def test_force_accept_records_what_a_negotiated_acceptance_records(
    db, fake_capacity, key_records
):
    """Administrative acceptance runs the domain's acceptance hooks: the credit
    terms and agreed price are recorded, and no unfunded quota hold is granted,
    exactly as after a negotiated acceptance."""
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
    class CapacityRuntime:
        async def reserve(self, _binding, *, claim, deal_ref, ttl_seconds):
            return {
                "capacity_reservation_id": "alloc-payment",
                "resource_id": "svc-quota",
                "allocated_units": claim["units"],
                "hold_expires_at": "2099-01-01 00:00",
            }

    monkeypatch.setattr(container.QUOTA_CAPACITY, "runtime", lambda _factory: CapacityRuntime())
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
        await place_quota_hold(SELLER_STAGES, {}, db, acceptance)

    hold = await db.load_capacity_hold(negotiation_id="neg-payment")
    assert hold["capacity_reservation_id"] == "alloc-payment"
    assert hold["payload"]["allocated_units"] == 3


def _payment_runtime(*, round_hook=None):
    """The runtime as a payments-composed storefront builds it."""
    return build_api_credit_negotiation_runtime(
        _DOMAIN,
        seller_round_hook=round_hook,
        accepted_obligation_dispatch={"arkhai.payments.v1": None},
        settlement_artifacts_builder=lambda agreement: {"mandate": {"amount": agreement["amount"]}},
    )


async def _start_payment(db, *, amount=250, quantity=3):
    """Open on a listing offering a payment option; the seller counters at the listed price."""
    await db.update_listing(
        listing_id="L-tok",
        settlement_options=[payment_option().model_dump(mode="json")],
    )
    selection = payment_selection()

    async def counter_at_listed_price(**_kwargs):
        return SellerRoundResult(
            our_amount=300,
            strategy_label="listed_price",
            direction="maximize",
            chain_label="payment-review",
            decision=NegotiationDecision(
                action="counter",
                proposal={
                    "fields": {"amount": 300},
                    "settlement_selection": selection.model_dump(mode="json"),
                },
            ),
            intermediate={"buyer_amount": amount, "uses_scalar_amount": True},
        )

    return await _payment_runtime(round_hook=counter_at_listed_price).start(
        repository=db,
        listing_id="L-tok",
        buyer_principal=BUYER_PRINCIPAL,
        seller_principal=SELLER_PRINCIPAL,
        proposal={
            "fields": {"amount": amount},
            "settlement_selection": selection.model_dump(mode="json"),
        },
        terms=terms(quantity),
        seller_agent_url="http://seller:8002",
        buyer_agent_url="http://buyer:9000",
        actor_principal=BUYER_PRINCIPAL,
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"mechanism": "alkahest.v1"},
        {"option_id": "f" * 64},
        {"expiration_unix": 1_900_000_001},
        {"params": {"payer_account": "33333333-3333-4333-8333-333333333333"}},
    ],
)
async def test_counter_rejects_opening_selection_switch(db, fake_capacity, key_records, changed):
    """A countered negotiation keeps the option and the mechanism inputs it opened with."""
    opening = await _start_payment(db)
    assert opening["action"] == "counter"
    changed_selection = {**payment_selection().model_dump(mode="json"), **changed}

    with pytest.raises(NegotiationStateError, match="opening settlement selection cannot change"):
        await _payment_runtime().continue_negotiation(
            repository=db,
            negotiation_id=opening["negotiation_id"],
            buyer_action="counter",
            buyer_proposal={"fields": {"amount": 300}, "settlement_selection": changed_selection},
            buyer_reason=None,
            buyer_principal=BUYER_PRINCIPAL,
            seller_principal=SELLER_PRINCIPAL,
            actor_principal=BUYER_PRINCIPAL,
            actor_role="buyer",
        )


async def test_accept_revalidates_the_current_trusted_listing_option(db, fake_capacity, key_records):
    """An option the seller withdrew after the opening cannot be accepted."""
    opening = await _start_payment(db)
    await db.update_listing(listing_id="L-tok", settlement_options=[])

    with pytest.raises(NegotiationStateError, match="no longer exact-matches the trusted listing"):
        await _payment_runtime().continue_negotiation(
            repository=db,
            negotiation_id=opening["negotiation_id"],
            buyer_action="accept",
            buyer_proposal=None,
            buyer_reason=None,
            buyer_principal=BUYER_PRINCIPAL,
            seller_principal=SELLER_PRINCIPAL,
            actor_principal=BUYER_PRINCIPAL,
            actor_role="buyer",
        )


async def _accept_as_proposed(*, history, **_round):
    """A seller policy that accepts the buyer's escrow as it stands."""
    proposal = dict(history[-1].proposal)
    return SellerRoundResult(
        our_amount=300,
        strategy_label="listed_price",
        direction="maximize",
        chain_label="accept_as_proposed",
        decision=NegotiationDecision(action="accept", proposal=proposal),
        intermediate={"uses_scalar_amount": True},
    )


@pytest.mark.parametrize(
    ("demands", "reason"),
    [
        pytest.param(
            [CONDITION], "release_condition_not_authorized", id="substituted recipient"
        ),
        pytest.param([], "release_condition_not_advertised", id="listing authorizes none"),
    ],
)
async def test_an_unauthorized_release_condition_is_refused_whatever_the_policy(
    db, fake_capacity, key_records, demands, reason
):
    """With a seller policy that accepts anything, the escrow is still held to
    the listing's release condition, and nothing is accepted."""
    await db.update_listing(listing_id="L-tok", demands=demands)
    substituted = proposal(300).model_copy(
        update={
            "demand": {**CONDITION, "demand_data": {"recipient": "0x" + "77" * 20}}
        }
    )

    with pytest.raises(OfferUnfulfillableError, match=reason):
        await build_api_credit_negotiation_runtime(
            _DOMAIN, seller_round_hook=_accept_as_proposed
        ).start(
            repository=db,
            listing_id="L-tok",
            buyer_principal=BUYER_PRINCIPAL,
            seller_principal=SELLER_PRINCIPAL,
            proposal=substituted,
            terms=terms(3),
            seller_agent_url="http://seller:8002",
            buyer_agent_url="http://buyer:9000",
            actor_principal=BUYER_PRINCIPAL,
        )

    with sqlite3.connect(db.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM negotiation_threads "
            "WHERE agreement_bytes IS NOT NULL OR settlement_plan IS NOT NULL"
        ).fetchone()[0] == 0
