"""An interrupted reveal on the VM storefront delivers to the seller once.

The buyer's first introduction start persists the introduction, then its
completion fails at the settlement runtime and the start answers 503. The
buyer's next start, a new request, completes the reveal and is the one start
that claims the seller-side delivery; every later start answers the durable
reveal and sends nothing. The operator's explicit re-delivery still sends.
Requests go through the production buyer's ``IntroductionTransport`` over
loopback HTTP, and the seller's delivery is the delivery kit's own, over one
recording sink.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from core_buyer.negotiation_client import AuthenticatedHTTPError
from market_contact_exchange import INTRODUCTION_COMPLETION_UNAVAILABLE
from market_delivery import ConfiguredSink, DeliveryEvent, SellerIntroductionDelivery

import market_storefront.container as container
from market_storefront.contact_exchange import build_vm_contact_exchange
from tests.introduction_deals import (
    BUYER_CONTACT,
    CONTACT_PUBLISHABLE,
    accept_introduction,
    introduction_transport,
    offer_introduction,
    publish,
)
from tests.loopback import serving
from tests.publication_app import SITE, SITE_CONTACTS, pool, publication_app

pytestmark = pytest.mark.asyncio

#: Bound on waiting for the background dispatch to reach the sink.
_SINK_WAIT_SECONDS = 5.0


class RecordingSink:
    """The seller's one configured sink: records each event it is handed."""

    def __init__(self) -> None:
        self.events: list[DeliveryEvent] = []
        self.received = threading.Event()

    def __call__(self, event: DeliveryEvent) -> None:
        self.events.append(event)
        self.received.set()


class CountingDelivery:
    """The seller's delivery, counting the dispatches the reveal schedules.

    The storefront calls the delivery inside the start request and the sinks
    run after it, so the count is settled when a start answers and shows that
    a later start scheduled nothing for the sink to receive.
    """

    def __init__(self, delivery: SellerIntroductionDelivery) -> None:
        self._delivery = delivery
        self.dispatches: list[str] = []

    def __call__(self, projection: Mapping[str, Any], agreement: Any) -> None:
        self.dispatches.append(str(projection["obligation_ref"]))
        self._delivery(projection, agreement)

    def redeliver(self, projection: Mapping[str, Any], agreement: Any):
        return self._delivery.redeliver(projection, agreement)


class CollectFailingOnce:
    """The storefront's settlement runtime, whose first collection fails.

    Every other operation, and every later collection, is the real runtime's
    over the app's database.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self.failures: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runtime, name)

    async def collect(self, **kwargs: Any) -> Any:
        if not self.failures:
            self.failures.append(kwargs["obligation_ref"])
            raise RuntimeError("settlement store unavailable")
        return await self._runtime.collect(**kwargs)


async def test_an_interrupted_reveal_is_delivered_to_the_seller_once(tmp_path) -> None:
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE: SITE_CONTACTS[SITE]},
    ) as world:
        sink = RecordingSink()
        delivery = CountingDelivery(
            SellerIntroductionDelivery((ConfiguredSink("recording", sink),))
        )
        runtime = CollectFailingOnce(world.composition.runtime)
        # Composed as the lifespan composes it, with the seller's delivery and
        # a settlement runtime whose first collection fails.
        contact_exchange = build_vm_contact_exchange(
            sqlite_client=world.db,
            settlement_composition=SimpleNamespace(
                settlement_config=world.composition.settlement_config,
                repository=world.composition.repository,
                runtime=runtime,
            ),
            known_origins=(SITE,),
            delivery=delivery,
        )
        container.resolved_contact_exchange = contact_exchange
        world.pools.append(pool("broker-a", backing="unbacked"))
        await offer_introduction(world, SITE, "broker-a")
        listing = (await publish(world))["broker-a"]
        negotiation_id, obligation_ref = await accept_introduction(world, listing)

        def start() -> dict[str, Any]:
            return introduction_transport(base_url).start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=dict(BUYER_CONTACT),
            )

        with serving(world.app) as base_url:
            with pytest.raises(AuthenticatedHTTPError) as interrupted:
                start()
            assert "503" in str(interrupted.value)
            assert INTRODUCTION_COMPLETION_UNAVAILABLE in str(interrupted.value)
            assert runtime.failures == [obligation_ref]
            assert await contact_exchange.store.load(obligation_ref) is not None
            assert delivery.dispatches == []

            revealed = start()
            assert revealed["revealed"] is True
            assert revealed["counterparty_contact"] == SITE_CONTACTS[SITE]
            assert delivery.dispatches == [obligation_ref]
            assert sink.received.wait(_SINK_WAIT_SECONDS)

            for _ in range(2):
                assert start()["revealed"] is True
            assert delivery.dispatches == [obligation_ref]

        (event,) = sink.events
        assert event.obligation_ref == obligation_ref
        assert event.role == "seller"
        assert event.contact == BUYER_CONTACT

        # The operator's explicit re-delivery reads the durable reveal and
        # sends it again, whatever the claim records.
        outcomes = delivery.redeliver(*await contact_exchange.seller_view(obligation_ref))
        assert [(outcome.sink, outcome.delivered) for outcome in outcomes] == [
            ("recording", True)
        ]
        assert [event.obligation_ref for event in sink.events] == [
            obligation_ref,
            obligation_ref,
        ]
        assert delivery.dispatches == [obligation_ref]
