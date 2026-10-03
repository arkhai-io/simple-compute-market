"""Recipient-side delivery of revealed marketplace events.

Each side of a deal delivers, to destinations its own operator configured, the
material that side already holds. Delivery is never authoritative: it cannot
fail a deal, cannot slow a counterparty, and carries no payload into a log.
"""

from .config import (
    RESERVED_SECTION_KEYS,
    SINK_KEY,
    DeliveryConfig,
    DeliveryRole,
    load_delivery_config,
    validate_delivery_origins,
)
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
from .seller import SellerIntroductionDelivery, build_seller_introduction_delivery
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
    "RESERVED_SECTION_KEYS",
    "SINK_ENTRY_POINT_GROUP",
    "SINK_KEY",
    "ConfiguredSink",
    "DeliveryConfig",
    "DeliveryConfigurationError",
    "DeliveryError",
    "DeliveryEvent",
    "DeliveryOutcome",
    "DeliveryRole",
    "DeliverySink",
    "DeliverySinkSet",
    "Role",
    "SellerIntroductionDelivery",
    "SinkFactory",
    "SinkSettings",
    "build_delivery_sinks",
    "build_seller_introduction_delivery",
    "canonical_principal",
    "deliver",
    "deliver_async",
    "describe_outcomes",
    "discover_sink_factories",
    "introduction_delivery_event",
    "load_delivery_config",
    "validate_delivery_origins",
]
