"""API-tokens concept modules: terms, pricing, reconciler, guards."""

from __future__ import annotations

import pytest

from domains.apitokens.listings.pricing import (
    determine_strategy_from_order,
    extract_unit_price_from_order,
)
from domains.apitokens.listings.reconciler import (
    listing_quota_resource_id,
    reopenable_token_listing_ids,
    stale_open_token_listing_ids,
)
from domains.apitokens.negotiation.policies import (
    api_tokens_round_zero_guard,
    key_owned_by_buyer_wallet,
    token_quota_guard,
)
from domains.apitokens.negotiation.terms import (
    make_api_tokens_provision_terms,
    provision_key_id,
    provision_key_mode,
    provision_quantity,
)
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationRound,
)

_TOKEN = "0x" + "01" * 20
_ESCROW = "0x" + "11" * 20
_BUYER = "0xBuyerAAAA0000000000000000000000000000ab"


def _offer(resource_id="svc-quota"):
    return {
        "kind": "api_tokens.v1",
        "service_name": "Acme Inference",
        "openapi_url": "https://api.acme.example/openapi.json",
        "base_url": "https://api.acme.example",
        "resource_id": resource_id,
    }


def _listing(resource_id="svc-quota", rate="100"):
    return {
        "listing_id": "L-tok",
        "status": "open",
        "offer_resource": _offer(resource_id),
        "accepted_escrows": [{
            "chain_name": "anvil",
            "escrow_address": _ESCROW,
            "literal_fields": {"token": _TOKEN},
            "rates": [{"field": "amount", "per": "token", "value": rate}],
        }],
    }


def _round0(proposal):
    return [NegotiationRound(
        round_number=0, sender="them", action="initial", proposal=proposal,
    )]


def _proposal(amount=300):
    return {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "fields": {"token": _TOKEN, "amount": amount},
        "literal_fields": {"token": _TOKEN},
        "rates": [{"field": "amount", "per": "token", "value": "100"}],
        "expiration_unix": 1_800_000_000,
    }


def _context(listing=None, *, resources=None, **intermediate):
    return NegotiationContext(
        direction="maximize",
        our_reference_amount=300.0,
        listing=listing or _listing(),
        available_resources={"resources": resources or []},
        intermediate=intermediate,
    )


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------

def test_provision_terms_round_trip():
    terms = make_api_tokens_provision_terms(
        quantity=5, key_mode="existing", key_id="ak_abc",
    )
    assert terms.kind == "api_tokens.v1"
    assert provision_quantity(terms) == 5
    assert provision_key_mode(terms) == "existing"
    assert provision_key_id(terms) == "ak_abc"

    # Carrier-agnostic: plain dicts off the wire parse the same.
    wire = terms.model_dump()
    assert provision_quantity(wire) == 5
    assert provision_key_mode(wire) == "existing"
    assert provision_key_id(wire) == "ak_abc"


def test_provision_terms_defaults():
    terms = make_api_tokens_provision_terms(quantity=1)
    assert provision_key_mode(terms) == "new"
    assert provision_key_id(terms) is None
    assert provision_quantity({}) is None
    assert provision_key_mode({}) == "new"


# ---------------------------------------------------------------------------
# Pricing / strategy
# ---------------------------------------------------------------------------

def test_unit_price_from_advertised_rate():
    assert extract_unit_price_from_order(_listing(rate="250")) == 250


def test_unit_price_hidden_reserve_falls_back_then_refuses():
    listing = _listing()
    listing["accepted_escrows"][0]["rates"] = []
    assert extract_unit_price_from_order(listing, default_min_price="7") == 7.0
    with pytest.raises(ValueError, match="hidden reserve"):
        extract_unit_price_from_order(listing)


def test_strategy_is_maximize_for_token_offers():
    assert determine_strategy_from_order(_listing()) == "maximize"
    assert determine_strategy_from_order({"offer_resource": {"gpu_model": "H200"}}) is None


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------

def test_reconciler_close_on_exhaustion_and_reopen():
    rows = [
        {**_listing("svc-a"), "listing_id": "L-a", "status": "open"},
        {**_listing("svc-b"), "listing_id": "L-b", "status": "open"},
        {**_listing("svc-a"), "listing_id": "L-c", "status": "closed"},
    ]
    availability = {(None, "svc-a"): 0, (None, "svc-b"): 12}
    assert stale_open_token_listing_ids(rows, availability=availability) == ["L-a"]
    assert reopenable_token_listing_ids(rows, availability=availability) == []

    availability = {(None, "svc-a"): 3, (None, "svc-b"): 12}
    assert stale_open_token_listing_ids(rows, availability=availability) == []
    assert reopenable_token_listing_ids(rows, availability=availability) == ["L-c"]


def test_reconciler_unknown_availability_is_conservative():
    rows = [{**_listing("svc-a"), "listing_id": "L-a", "status": "open"}]
    # Authority unreachable: close nothing, reopen nothing.
    assert stale_open_token_listing_ids(rows, availability=None) == []
    assert reopenable_token_listing_ids(rows, availability=None) == []
    # Resource gone from the ledger: the listing must not stay open.
    assert stale_open_token_listing_ids(rows, availability={}) == ["L-a"]


def test_reconciler_ignores_non_token_listings():
    rows = [{
        "listing_id": "L-vm", "status": "open",
        "offer_resource": {"gpu_model": "H200"},
    }]
    assert stale_open_token_listing_ids(rows, availability={}) == []
    assert listing_quota_resource_id(rows[0]) is None


# ---------------------------------------------------------------------------
# Round-zero guard
# ---------------------------------------------------------------------------

def test_round_zero_guard_requires_valid_quantity():
    decision, _ = api_tokens_round_zero_guard(
        _round0(_proposal()), _context(requested_quantity=None),
    )
    assert decision.action == "reject"
    assert "token_quantity_missing" in decision.reason

    decision, _ = api_tokens_round_zero_guard(
        _round0(_proposal()), _context(requested_quantity=0),
    )
    assert decision.action == "reject"
    assert "token_quantity_invalid" in decision.reason


def test_round_zero_guard_validates_key_disposition():
    decision, _ = api_tokens_round_zero_guard(
        _round0(_proposal()),
        _context(requested_quantity=3, key_mode="existing", key_id=None),
    )
    assert decision.action == "reject"
    assert "key_disposition_invalid" in decision.reason


def test_round_zero_guard_passes_and_canonicalizes():
    context = _context(requested_quantity=3, key_mode="new")
    decision, context = api_tokens_round_zero_guard(_round0(_proposal()), context)
    assert decision is None
    assert context.intermediate["uses_scalar_amount"] is True
    assert context.intermediate["accepted_escrow_proposal"]["fields"]["amount"] == 300


def test_round_zero_guard_rejects_missing_amount():
    proposal = _proposal()
    del proposal["fields"]["amount"]
    decision, _ = api_tokens_round_zero_guard(
        _round0(proposal), _context(requested_quantity=3),
    )
    assert decision.action == "reject"
    assert "missing_amount" in decision.reason


def test_round_zero_guard_only_fires_on_round_zero():
    history = _round0(_proposal())
    history.append(NegotiationRound(
        round_number=1, sender="us", action="counter", proposal=_proposal(),
    ))
    decision, _ = api_tokens_round_zero_guard(history, _context())
    assert decision is None


# ---------------------------------------------------------------------------
# Quota guard
# ---------------------------------------------------------------------------

def test_quota_guard_passes_when_covered_and_rejects_when_not():
    resources = [{"resource_id": "svc-quota", "available_units": 5}]
    decision, _ = token_quota_guard(
        _round0(_proposal()),
        _context(resources=resources, requested_quantity=5),
    )
    assert decision is None

    decision, _ = token_quota_guard(
        _round0(_proposal()),
        _context(resources=resources, requested_quantity=6),
    )
    assert decision.action == "reject"
    assert decision.reason.startswith("quota_exhausted")


def test_quota_guard_matches_by_resource_id():
    resources = [
        {"resource_id": "other", "available_units": 100},
        {"resource_id": "svc-quota", "available_units": 2},
    ]
    decision, _ = token_quota_guard(
        _round0(_proposal()),
        _context(resources=resources, requested_quantity=3),
    )
    assert decision.action == "reject"


def test_quota_guard_ignores_non_token_listings():
    decision, _ = token_quota_guard(
        _round0(_proposal()),
        _context(listing={"offer_resource": {"gpu_model": "H200"}},
                 requested_quantity=3),
    )
    assert decision is None


# ---------------------------------------------------------------------------
# Ownership guard
# ---------------------------------------------------------------------------

def _owned_record(owner=_BUYER, scheme="wallet", status="active"):
    return {"key_id": "ak_x", "owner_scheme": scheme, "owner_id": owner,
            "status": status}


def test_ownership_guard_passes_new_key_deals():
    decision, _ = key_owned_by_buyer_wallet(
        _round0(_proposal()), _context(key_mode="new"),
    )
    assert decision is None


def test_ownership_guard_admits_owner_wallet_case_insensitively():
    decision, _ = key_owned_by_buyer_wallet(
        _round0(_proposal()),
        _context(
            key_mode="existing", key_id="ak_x",
            key_record=_owned_record(owner=_BUYER.upper().replace("0X", "0x")),
            buyer_wallet=_BUYER.lower(),
        ),
    )
    assert decision is None


def test_ownership_guard_rejects_stranger():
    decision, _ = key_owned_by_buyer_wallet(
        _round0(_proposal()),
        _context(
            key_mode="existing", key_id="ak_x",
            key_record=_owned_record(),
            buyer_wallet="0x" + "99" * 20,
        ),
    )
    assert decision.action == "reject"
    assert decision.reason.startswith("key_not_owned")


def test_ownership_guard_rejects_unknown_and_revoked_keys():
    decision, _ = key_owned_by_buyer_wallet(
        _round0(_proposal()),
        _context(key_mode="existing", key_id="ak_x", key_record=None,
                 buyer_wallet=_BUYER),
    )
    assert decision.reason.startswith("key_not_found")

    decision, _ = key_owned_by_buyer_wallet(
        _round0(_proposal()),
        _context(
            key_mode="existing", key_id="ak_x",
            key_record=_owned_record(status="revoked"),
            buyer_wallet=_BUYER,
        ),
    )
    assert decision.reason.startswith("key_revoked")


def test_ownership_guard_open_key_admits_anyone():
    record = {"key_id": "ak_x", "owner_scheme": None, "owner_id": None,
              "status": "active"}
    decision, _ = key_owned_by_buyer_wallet(
        _round0(_proposal()),
        _context(key_mode="existing", key_id="ak_x", key_record=record,
                 buyer_wallet="0x" + "99" * 20),
    )
    assert decision is None


def test_ownership_guard_rejects_unverifiable_schemes():
    decision, _ = key_owned_by_buyer_wallet(
        _round0(_proposal()),
        _context(
            key_mode="existing", key_id="ak_x",
            key_record=_owned_record(scheme="ed25519", owner="pubkey"),
            buyer_wallet=_BUYER,
        ),
    )
    assert decision.action == "reject"
    assert "not verifiable" in decision.reason
