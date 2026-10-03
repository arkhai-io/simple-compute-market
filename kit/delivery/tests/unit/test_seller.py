"""Seller-side dispatch routes each reveal by its origin, off the request path."""

from __future__ import annotations

import asyncio
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


async def _settle() -> None:
    for _ in range(100):
        await asyncio.sleep(0.01)


async def test_a_reveal_reaches_only_its_origins_instances() -> None:
    received: dict = {}
    delivery = _delivery(received, ROUTES)
    delivery(PROJECTION, Agreement("neg-1", BUYER, "dc-west"))
    await _settle()
    assert sorted(received) == ["audit", "west-hook"]
    (event,) = received["west-hook"]
    assert event.role == "seller"
    assert event.contact == {"email": "buyer@example.com"}


async def test_an_unrouted_origin_receives_nothing() -> None:
    received: dict = {}
    _delivery(received, ROUTES)(PROJECTION, Agreement("neg-1", BUYER, "dc-north"))
    await _settle()
    assert received == {}


async def test_without_routing_every_instance_receives_every_reveal() -> None:
    received: dict = {}
    _delivery(received)(PROJECTION, Agreement("neg-1", BUYER, "default"))
    await _settle()
    assert sorted(received) == ["audit", "east-hook", "west-hook"]


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
