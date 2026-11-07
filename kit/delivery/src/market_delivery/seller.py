"""Seller-side delivery of a revealed introduction.

A storefront learns the buyer's contact at the moment it serves the reveal,
and the seller is the one who wants to be told. Dispatch runs off the request
path: the response is already determined when it starts, so a counterparty's
request never waits on a seller's mail server or API.

This module reads the reveal and the agreement by shape -- the agreement's
``agreement_ref``, ``buyer_principal``, and ``origin`` -- rather than importing
the mechanism that produced them, as the event constructor reads a reveal.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection, Mapping
from typing import Any

from market_identity import Signer

from .config import DeliveryConfig, validate_delivery_origins
from .discovery import build_delivery_sinks
from .dispatch import DeliveryOutcome, deliver, deliver_async
from .events import introduction_delivery_event
from .sinks import ConfiguredSink

_logger = logging.getLogger(__name__)


class SellerIntroductionDelivery:
    """Route each revealed introduction to its origin's configured instances."""

    def __init__(
        self,
        sinks: tuple[ConfiguredSink, ...],
        *,
        origins: Mapping[str, tuple[str, ...]] | None = None,
        logger: logging.Logger = _logger,
    ) -> None:
        self._sinks = sinks
        self._origins = (
            {origin: frozenset(names) for origin, names in origins.items()}
            if origins is not None
            else None
        )
        self._logger = logger
        # Tasks are retained until they finish: an unreferenced task can be
        # collected mid-flight, and a delivery that vanishes silently is worse
        # than one that fails loudly.
        self._pending: set[asyncio.Task] = set()

    @property
    def sinks(self) -> tuple[ConfiguredSink, ...]:
        return self._sinks

    def sinks_for(self, origin: str | None) -> tuple[ConfiguredSink, ...]:
        """The instances routed for ``origin``; every instance when unrouted.

        An origin a routing table does not name receives nothing rather than
        another origin's destinations.
        """

        if self._origins is None:
            return self._sinks
        routed = self._origins.get(origin) if origin is not None else None
        if not routed:
            return ()
        return tuple(sink for sink in self._sinks if sink.name in routed)

    def _event(self, projection: Mapping[str, Any], agreement: Any) -> Any:
        return introduction_delivery_event(
            projection,
            role="seller",
            agreement_ref=agreement.agreement_ref,
            counterparty=agreement.buyer_principal,
        )

    def __call__(self, projection: Mapping[str, Any], agreement: Any) -> None:
        """Schedule delivery of one fresh reveal and return at once."""

        sinks = self.sinks_for(getattr(agreement, "origin", None))
        if not sinks:
            return
        task = asyncio.create_task(deliver_async(sinks, self._event(projection, agreement)))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        task.add_done_callback(self._log_outcomes)

    def redeliver(
        self, projection: Mapping[str, Any], agreement: Any
    ) -> tuple[DeliveryOutcome, ...]:
        """Send an already-revealed introduction to its origin's instances again.

        The explicit operator action behind a failed send. It runs inline
        rather than in the background: whoever asked for it is present and
        waiting to learn whether it worked this time.
        """

        sinks = self.sinks_for(getattr(agreement, "origin", None))
        return deliver(sinks, self._event(projection, agreement))

    def _log_outcomes(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            # deliver_async does not raise, so this is the scheduling itself
            # failing; the class alone is reported, never what was carried.
            self._logger.warning("introduction delivery failed: %s", type(error).__name__)
            return
        for outcome in task.result() or ():
            level = logging.INFO if outcome.delivered else logging.WARNING
            self._logger.log(
                level, "introduction %s: %s", outcome.obligation_ref, outcome.describe()
            )


def build_seller_introduction_delivery(
    config: DeliveryConfig,
    *,
    known_origins: Collection[str],
    signer: Signer | None = None,
    factories: Mapping[str, Any] | None = None,
    logger: logging.Logger = _logger,
) -> SellerIntroductionDelivery | None:
    """Build a storefront's seller-side delivery, or None when nothing is enabled.

    Fails at startup on the operator's own mistake: an uninstalled or
    misconfigured instance, or routing that does not fit the storefront's
    origins.
    """

    validate_delivery_origins(config, known_origins)
    sink_set = build_delivery_sinks(config, factories=factories, signer=signer)
    for warning in sink_set.warnings:
        logger.warning("%s", warning)
    if not sink_set.sinks:
        return None
    return SellerIntroductionDelivery(
        sink_set.sinks, origins=config.origins, logger=logger
    )


__all__ = ["SellerIntroductionDelivery", "build_seller_introduction_delivery"]
