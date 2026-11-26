"""The service composes its event-sink consumer as its own sender.

Composition only: no event is recorded or delivered. A webhook instance that
signs is built only when the composition hands the kit both the service's
signer and the role and operation it signs event deliveries as; the kit refuses
either missing.
"""

from __future__ import annotations

import pytest
from market_delivery import DeliveryConfigurationError
from market_identity import Ed25519Signer
from sqlalchemy.orm import sessionmaker

from compute_provisioning_service.services.operator_events import (
    EVENT_DELIVERY_SIGNING,
    EventsSettings,
    event_catalogue,
    event_sink_consumer,
)

# A deterministic development signing key; never used on a network.
_SIGNER = Ed25519Signer(b"p" * 32)

_SIGNING_HOOK = EventsSettings.model_validate({
    "sinks": {
        "enabled": ["ops-hook"],
        "ops-hook": {"sink": "webhook", "url": "https://hooks.example.invalid/events", "sign": True},
    },
    "routes": {"held-work": {"where": "severity = 'action_required'", "sinks": ["ops-hook"]}},
})


def test_a_signing_webhook_signs_event_deliveries_as_the_provisioning_service() -> None:
    assert (EVENT_DELIVERY_SIGNING.role, EVENT_DELIVERY_SIGNING.operation) == (
        "service", "operator_event_delivery",
    )
    consumer = event_sink_consumer(
        sessionmaker(), event_catalogue(_SIGNER), _SIGNING_HOOK, signer=_SIGNER, instance="fixture-site",
    )
    assert consumer.name == "event-sinks"
    assert consumer.runner == "compute-provisioning:fixture-site"


def test_a_signing_webhook_without_the_service_signer_is_refused() -> None:
    with pytest.raises(DeliveryConfigurationError, match="ops-hook"):
        event_sink_consumer(
            sessionmaker(), event_catalogue(_SIGNER), _SIGNING_HOOK, signer=None, instance="fixture-site",
        )
