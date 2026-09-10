"""The event carries the reveal verbatim and renders it readably."""

from __future__ import annotations

import pytest
from market_delivery import (
    INTRODUCTION_REVEALED,
    canonical_principal,
    introduction_delivery_event,
)
from market_identity import Identity, IdentityScheme

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
    assert (
        introduction_delivery_event(
            _projection(),
            role="buyer",
            agreement_ref="agreement-1",
            counterparty=SELLER,
        ).rendered
        == body
    )


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


def test_nested_context_is_readable_without_domain_or_template_interpretation() -> None:
    text = "  Whole blurb 😀 e\u0301\n{{ untouched }} <b>plain</b> ${inert}  "
    context = {
        "listing_id": "declared-contact-example",
        "accepted_context": {
            "declaration": {
                "name": "Example machine",
                "machine_details": {"gpu_count": 2},
            },
            "accepted_terms": {"duration_seconds": 3600, "access_method": "none"},
        },
        "opaque_list": [{"label": "{{ literal }}\n<plain>"}, "second"],
    }
    event = introduction_delivery_event(
        _projection(introduction=context, counterparty_contact={"text": text}),
        role="seller",
    )
    assert event.context == context and event.contact == {"text": text}
    assert event.rendered.endswith("Counterparty contact:\n  text: " + text)
    assert (
        "  accepted_context:\n"
        "    accepted_terms:\n"
        "      access_method: none\n"
        "      duration_seconds: 3600\n"
        "    declaration:\n"
        "      machine_details:\n"
        "        gpu_count: 2\n"
        "      name: Example machine"
    ) in event.rendered
    assert (
        "  opaque_list:\n    0:\n      label: {{ literal }}\n<plain>\n    1: second"
        in event.rendered
    )
    reordered = {key: context[key] for key in reversed(context)}
    assert (
        introduction_delivery_event(
            _projection(introduction=reordered, counterparty_contact={"text": text}),
            role="seller",
        ).rendered
        == event.rendered
    )
