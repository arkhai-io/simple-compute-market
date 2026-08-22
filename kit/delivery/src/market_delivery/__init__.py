"""Recipient-side delivery of revealed marketplace events.

Each side of a deal delivers, to destinations its own operator configured, the
material that side already holds. Delivery is never authoritative: it cannot
fail a deal, cannot slow a counterparty, and carries no payload into a log.
"""

from .config import DeliveryConfig, load_delivery_config
from .discovery import (
    DeliverySinkSet,
    build_delivery_sinks,
    discover_sink_factories,
)
from .dispatch import DeliveryOutcome, deliver, deliver_async, describe_outcomes
from .events import (
    INTRODUCTION_REVEALED,
    DeliveryEvent,
    Role,
    canonical_principal,
    introduction_delivery_event,
)
from .sinks import (
    DEFAULT_TIMEOUT_SECONDS,
    SINK_ENTRY_POINT_GROUP,
    ConfiguredSink,
    DeliveryConfigurationError,
    DeliveryError,
    DeliverySink,
    SinkFactory,
    SinkSettings,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "INTRODUCTION_REVEALED",
    "SINK_ENTRY_POINT_GROUP",
    "ConfiguredSink",
    "DeliveryConfig",
    "DeliveryConfigurationError",
    "DeliveryError",
    "DeliveryEvent",
    "DeliveryOutcome",
    "DeliverySink",
    "DeliverySinkSet",
    "Role",
    "SinkFactory",
    "SinkSettings",
    "build_delivery_sinks",
    "canonical_principal",
    "deliver",
    "deliver_async",
    "describe_outcomes",
    "discover_sink_factories",
    "introduction_delivery_event",
    "load_delivery_config",
]
