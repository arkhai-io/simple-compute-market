"""Seller-side delivery of a revealed introduction.

The storefront learns the buyer's contact at the moment it serves the reveal,
and its own operator is the one who wants to be told. Dispatch runs off the
request path: the response is already determined when it starts, so a
counterparty's request never waits on this operator's mail server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Mapping
from typing import Any

from market_contact_exchange import (
    DeliverIntroduction,
    IntroductionAgreement,
    introduction_projection,
)
from market_delivery import (
    ConfiguredSink,
    DeliveryOutcome,
    DeliverySinkSet,
    build_delivery_sinks,
    deliver,
    deliver_async,
    introduction_delivery_event,
    load_delivery_config,
)

from .introduction_routes import load_revealed_introduction

logger = logging.getLogger(__name__)

DELIVERY_ENVIRONMENT_VARIABLE = "BARE_METAL_STOREFRONT_DELIVERY"


def load_storefront_delivery_sinks(
    section: Mapping[str, Any] | None,
) -> DeliverySinkSet:
    """Build the operator's sink set, failing at startup on their own mistake."""

    sinks = build_delivery_sinks(load_delivery_config(section))
    for warning in sinks.warnings:
        logger.warning("%s", warning)
    return sinks


def _log_outcomes(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        # deliver_async does not raise, so this is the scheduling itself
        # failing; the class alone is reported, never what was being carried.
        logger.warning("introduction delivery failed: %s", type(error).__name__)
        return
    for outcome in task.result() or ():
        if outcome.delivered:
            logger.info(
                "introduction %s: %s", outcome.obligation_ref, outcome.describe()
            )
        else:
            logger.warning(
                "introduction %s: %s", outcome.obligation_ref, outcome.describe()
            )


def build_introduction_delivery(
    sinks: tuple[ConfiguredSink, ...],
) -> DeliverIntroduction | None:
    """Return the dispatch injected into the reveal service, or nothing."""

    if not sinks:
        return None
    # Tasks are retained until they finish: an unreferenced task can be
    # collected mid-flight, and a delivery that vanishes silently is worse
    # than one that fails loudly.
    pending: set[asyncio.Task] = set()

    def dispatch(
        projection: Mapping[str, Any],
        agreement: IntroductionAgreement,
    ) -> None:
        event = introduction_delivery_event(
            projection,
            role="seller",
            agreement_ref=agreement.agreement_ref,
            counterparty=agreement.buyer_principal,
        )
        task = asyncio.create_task(deliver_async(sinks, event))
        pending.add(task)
        task.add_done_callback(pending.discard)
        task.add_done_callback(_log_outcomes)

    return dispatch


def storefront_delivery_section() -> Mapping[str, Any] | None:
    """Read the ``[Delivery]`` section from this storefront's own configuration.

    The bare-metal storefront is configured by environment, the same way its
    settlement section arrives, so the carrier differs from the buyer's file
    while the section shape is identical.
    """

    raw = os.environ.get(DELIVERY_ENVIRONMENT_VARIABLE, "").strip()
    if not raw:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, Mapping):
        raise TypeError("delivery configuration must be a JSON object")
    return parsed


async def redeliver_introduction(
    db: Any,
    obligation_ref: str,
    sinks: tuple[ConfiguredSink, ...],
) -> tuple[DeliveryOutcome, ...]:
    """Send an already-revealed introduction to this operator's sinks again.

    The explicit operator action behind a failed send. It runs inline rather
    than in the background: whoever asked for it is present and waiting to
    learn whether it worked this time.
    """

    record, agreement = await load_revealed_introduction(db, obligation_ref)
    event = introduction_delivery_event(
        introduction_projection(record, for_role="seller"),
        role="seller",
        agreement_ref=agreement.agreement_ref,
        counterparty=agreement.buyer_principal,
    )
    return deliver(sinks, event)


__all__ = [
    "DELIVERY_ENVIRONMENT_VARIABLE",
    "build_introduction_delivery",
    "load_storefront_delivery_sinks",
    "redeliver_introduction",
    "storefront_delivery_section",
]
