"""Buyer-side delivery of a revealed introduction.

The buyer already holds the seller's contact the moment the reveal returns,
and the buyer's own operator is the one who wants it somewhere convenient. A
command has no supervisor to outlive it, so sinks run inline -- but the
introduction is printed first, because a slow sink must never delay or obscure
the answer the operator came for.

Delivery is resolved through the installed-plugin contract, so this package
gains no dependency on any settlement mechanism.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from market_config.config_loader import get_dotted, load_user_config
from market_delivery import (
    DeliveryOutcome,
    DeliverySinkSet,
    build_delivery_sinks,
    deliver,
    introduction_delivery_event,
    load_delivery_config,
)
from market_identity import Identity

DELIVERY_CONFIG_PATH = "delivery"


def buyer_delivery_section(
    config_path: str | None = None,
) -> Mapping[str, Any] | None:
    """Read ``[Delivery]`` from the buyer's own layered configuration."""

    document = load_user_config(Path(config_path) if config_path else None)
    section = get_dotted(document, DELIVERY_CONFIG_PATH)
    return section if isinstance(section, Mapping) else None


def load_buyer_delivery_sinks(config_path: str | None = None) -> DeliverySinkSet:
    """Build the buyer's sink set, failing on their own configuration mistake."""

    return build_delivery_sinks(load_delivery_config(buyer_delivery_section(config_path)))


def deliver_introduction(
    projection: Mapping[str, Any],
    *,
    sinks: DeliverySinkSet,
    agreement_ref: str | None = None,
    counterparty: Identity | None = None,
) -> tuple[DeliveryOutcome, ...]:
    """Hand one revealed introduction to the buyer's configured sinks."""

    if not sinks.sinks:
        return ()
    event = introduction_delivery_event(
        projection,
        role="buyer",
        agreement_ref=agreement_ref,
        counterparty=counterparty,
    )
    return deliver(sinks.sinks, event)


def report_delivery(
    outcomes: tuple[DeliveryOutcome, ...],
    warnings: tuple[str, ...] = (),
    *,
    stream: Any = None,
) -> None:
    """Tell the operator what happened, on the stream that is not the answer.

    Outcomes and warnings carry a sink name, a deal reference, and a failure
    the sink made safe -- never the payload -- so this is printable wherever
    the operator is watching.
    """

    target = stream if stream is not None else sys.stderr
    for warning in warnings:
        print(f"delivery: {warning}", file=target)
    for outcome in outcomes:
        print(f"delivery: {outcome.describe()}", file=target)


__all__ = [
    "DELIVERY_CONFIG_PATH",
    "buyer_delivery_section",
    "deliver_introduction",
    "load_buyer_delivery_sinks",
    "report_delivery",
]
