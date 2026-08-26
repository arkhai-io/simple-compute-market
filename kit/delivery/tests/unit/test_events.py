"""The event carries the reveal verbatim and renders it readably."""

from __future__ import annotations

import pytest
from market_identity import Identity, IdentityScheme

from market_delivery import (
    INTRODUCTION_REVEALED,
    canonical_principal,
    introduction_delivery_event,
)

SELLER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "ab" * 20)


def _projection(**overrides):
    projection = {
        "obligation_ref": "a" * 64,
        "mechanism": "contact-exchange.v1",
        "revealed": True,
        "introduction": {
            "option_id": "b" * 64,
            "profile": "default",
            "channel": "telegram",
            "terms": "hourly, invoiced monthly",
            "listing_id": "listing-1",
        },
        "counterparty_contact": {"telegram": "@seller", "zulip": "seller@example"},
    }
    projection.update(overrides)
    return projection


def test_unfamiliar_contact_keys_survive_verbatim() -> None:
    event = introduction_delivery_event(
        _projection(counterparty_contact={"carrier-pigeon": "loft 4", "sms": "+100"}),
        role="buyer",
        agreement_ref="agreement-1",
        counterparty=SELLER,
    )

    assert event.kind == INTRODUCTION_REVEALED
    assert event.contact == {"carrier-pigeon": "loft 4", "sms": "+100"}
    assert event.counterparty == f"eip191:{SELLER.identifier}"
    assert "carrier-pigeon: loft 4" in event.rendered
    assert "sms: +100" in event.rendered


def test_rendering_is_stable_and_carries_the_agreed_context() -> None:
    event = introduction_delivery_event(
        _projection(), role="buyer", agreement_ref="agreement-1", counterparty=SELLER
    )

    assert event.rendered.splitlines()[0] == "Introduction revealed"
    assert f"Deal: {'a' * 64}" in event.rendered
    assert "Agreement: agreement-1" in event.rendered
    assert "You are the: buyer" in event.rendered
    assert "channel: telegram" in event.rendered
    assert "terms: hourly, invoiced monthly" in event.rendered
    body = event.rendered
    assert body.index("listing_id:") < body.index("option_id:") < body.index("channel:")
    assert introduction_delivery_event(
        _projection(), role="buyer", agreement_ref="agreement-1", counterparty=SELLER
    ).rendered == body


def test_each_side_names_its_own_role() -> None:
    seller_side = introduction_delivery_event(_projection(), role="seller")

    assert seller_side.role == "seller"
    assert seller_side.counterparty is None
    assert "You are the: seller" in seller_side.rendered


def test_an_unrevealed_or_anonymous_projection_is_refused() -> None:
    with pytest.raises(ValueError, match="revealed"):
        introduction_delivery_event(_projection(revealed=False), role="buyer")
    with pytest.raises(ValueError, match="obligation reference"):
        introduction_delivery_event(_projection(obligation_ref=""), role="buyer")


def test_payload_round_trips_as_json_safe_structure() -> None:
    payload = introduction_delivery_event(_projection(), role="buyer").payload()

    assert payload["kind"] == INTRODUCTION_REVEALED
    assert payload["contact"]["telegram"] == "@seller"
    assert payload["rendered"].startswith("Introduction revealed")


def test_canonical_principal_of_nothing_is_nothing() -> None:
    assert canonical_principal(None) is None
