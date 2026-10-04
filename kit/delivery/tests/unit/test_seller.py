"""Seller-side routing and re-delivery, with no background dispatch involved.

Which instances a reveal reaches is decided by ``sinks_for`` alone, so routing is
tested there directly; re-delivery runs inline. The background dispatch itself is
covered at integration level.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from market_identity import Identity, IdentityScheme

from market_delivery import (
    ConfiguredSink,
    DeliveryConfigurationError,
    SellerIntroductionDelivery,
    build_seller_introduction_delivery,
    load_delivery_config,
)

BUYER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "11" * 20)
PROJECTION = {
    "obligation_ref": "a" * 64,
    "revealed": True,
    "introduction": {"channel": "email"},
    "counterparty_contact": {"email": "buyer@example.com"},
}


@dataclass(frozen=True)
class Agreement:
    agreement_ref: str
    buyer_principal: Identity
    origin: str | None


def _recorder(name: str, received: dict) -> ConfiguredSink:
    return ConfiguredSink(
        name=name, sink=lambda event: received.setdefault(name, []).append(event)
    )


def _delivery(received: dict, origins=None) -> SellerIntroductionDelivery:
    return SellerIntroductionDelivery(
        tuple(_recorder(name, received) for name in ("west-hook", "east-hook", "audit")),
        origins=origins,
    )


ROUTES = {"dc-west": ("west-hook", "audit"), "dc-east": ("east-hook", "audit")}


def _names(sinks) -> list[str]:
    return [sink.name for sink in sinks]


def test_a_routed_origin_reaches_only_its_instances() -> None:
    assert _names(_delivery({}, ROUTES).sinks_for("dc-west")) == ["west-hook", "audit"]


def test_an_unrouted_origin_reaches_nothing() -> None:
    delivery = _delivery({}, ROUTES)
    assert delivery.sinks_for("dc-north") == ()
    assert delivery.sinks_for(None) == ()


def test_without_routing_every_instance_receives_every_reveal() -> None:
    assert _names(_delivery({}).sinks_for("default")) == ["west-hook", "east-hook", "audit"]


def test_an_unrouted_reveal_schedules_nothing() -> None:
    """With no instance for its origin, dispatch returns without scheduling, so
    it needs no running event loop at all."""
    received: dict = {}
    _delivery(received, ROUTES)(PROJECTION, Agreement("neg-1", BUYER, "dc-north"))
    assert received == {}


def test_redelivery_routes_by_origin_and_reports_outcomes() -> None:
    received: dict = {}
    outcomes = _delivery(received, ROUTES).redeliver(
        PROJECTION, Agreement("neg-1", BUYER, "dc-east")
    )
    assert [outcome.sink for outcome in outcomes] == ["east-hook", "audit"]
    assert all(outcome.delivered for outcome in outcomes)


def test_a_multi_origin_storefront_must_route() -> None:
    config = load_delivery_config(
        {"enabled": ["file"], "file": {"path": "/tmp/x"}}, role="seller"
    )
    with pytest.raises(DeliveryConfigurationError, match="needs a \\[Delivery.origins\\]"):
        build_seller_introduction_delivery(
            config, known_origins={"dc-west", "dc-east"}, factories={}
        )


def test_nothing_enabled_builds_no_delivery() -> None:
    assert (
        build_seller_introduction_delivery(
            load_delivery_config(None, role="seller"), known_origins={"default"}
        )
        is None
    )
