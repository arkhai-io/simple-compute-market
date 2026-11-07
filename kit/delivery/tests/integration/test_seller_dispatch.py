"""Seller-side dispatch runs off the request path and reaches its origin's instances.

The sinks are real callables run by the real background dispatch; the test
waits on what they record rather than on time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from market_identity import Identity, IdentityScheme

from market_delivery import ConfiguredSink, SellerIntroductionDelivery

BUYER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "11" * 20)
PROJECTION = {
    "obligation_ref": "a" * 64,
    "revealed": True,
    "introduction": {"channel": "email"},
    "counterparty_contact": {"email": "buyer@example.com"},
}
ROUTES = {"dc-west": ("west-hook", "audit"), "dc-east": ("east-hook", "audit")}


@dataclass(frozen=True)
class Agreement:
    agreement_ref: str
    buyer_principal: Identity
    origin: str | None


async def test_a_reveal_is_delivered_in_the_background_to_its_origin_only() -> None:
    loop = asyncio.get_running_loop()
    received: dict[str, list] = {}
    expected = {"west-hook", "audit"}
    arrived = asyncio.Event()

    def recorder(name: str) -> ConfiguredSink:
        def sink(event) -> None:
            # Sinks run on a worker thread; the event loop is told from there.
            received.setdefault(name, []).append(event)
            if set(received) >= expected:
                loop.call_soon_threadsafe(arrived.set)

        return ConfiguredSink(name=name, sink=sink)

    delivery = SellerIntroductionDelivery(
        tuple(recorder(name) for name in ("west-hook", "east-hook", "audit")),
        origins=ROUTES,
    )

    delivery(PROJECTION, Agreement("neg-1", BUYER, "dc-west"))

    await asyncio.wait_for(arrived.wait(), timeout=5)
    # The dispatch task outlives the sinks' last call by its own completion; let it
    # finish before the loop closes rather than leave it pending.
    await asyncio.wait_for(asyncio.gather(*delivery._pending), timeout=5)
    assert set(received) == expected
    (event,) = received["west-hook"]
    assert event.role == "seller"
    assert event.contact == {"email": "buyer@example.com"}
