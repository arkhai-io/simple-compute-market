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
    discover_sink_settings_models,
)
from .dispatch import (
    DeliveryOutcome,
    deliver,
    deliver_async,
    deliver_one,
    describe_outcomes,
)
from .events import (
    INTRODUCTION_REVEALED,
    DeliveryEvent,
    Role,
    canonical_principal,
    introduction_delivery_event,
)
from .seller import (
    INTRODUCTION_SIGNING,
    SellerIntroductionDelivery,
    build_seller_introduction_delivery,
)
from .sinks import (
    DEFAULT_TIMEOUT_SECONDS,
    SINK_ENTRY_POINT_GROUP,
    ConfiguredSink,
    DeclaredSink,
    Deliverable,
    DeliveryConfigurationError,
    DeliveryError,
    DeliverySink,
    SigningAs,
    SinkFactory,
    SinkSettings,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "INTRODUCTION_REVEALED",
    "INTRODUCTION_SIGNING",
    "RESERVED_SECTION_KEYS",
    "SINK_ENTRY_POINT_GROUP",
    "SINK_KEY",
    "ConfiguredSink",
    "DeclaredSink",
    "Deliverable",
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
    "SigningAs",
    "SinkFactory",
    "SinkSettings",
    "build_delivery_sinks",
    "build_seller_introduction_delivery",
    "canonical_principal",
    "deliver",
    "deliver_async",
    "deliver_one",
    "describe_outcomes",
    "discover_sink_factories",
    "discover_sink_settings_models",
    "introduction_delivery_event",
    "load_delivery_config",
    "validate_delivery_origins",
]
