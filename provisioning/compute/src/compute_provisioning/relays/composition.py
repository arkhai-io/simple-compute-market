"""What the relays contribute to the provisioning service's composition.

The release effect, the reconciliation worker, and the relay definitions
document belong to every domain a relay carries, so the service registers them
once, through ``relay_contribution``, beside the domains' own bundles. A
domain's share is only what it does with a lease: its plan's allocation call,
its codec's reading of the relay endpoint, and its playbook's proxy. The
composition root reads its configuration and passes the values in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..composition import ExecutorAdapterBundle
from ..definition_documents import DefinitionDocumentContribution
from ..startup import ComputeProvisioningBackgroundTask
from .allocator import (
    RelayPortAllocator,
    fulfillment_lease_owner_is_released,
    release_reservation_ports,
)
from .definitions import relay_definitions_document
from .service import RelayService

#: The name the relay contribution composes under.
RELAY_CONTRIBUTION = "relays"


@dataclass(frozen=True)
class RelayReconciliationSchedule:
    """How often the backstop sweeps, and how long a released reservation's
    lease is left to the release effect before the sweep returns it."""

    poll_interval_seconds: float
    grace_seconds: float


def relay_definitions(
    *, relay_service: RelayService, settings: Any, path: Path | None
) -> DefinitionDocumentContribution:
    """The relay definitions document at ``path``, or none mounted.

    ``settings`` is the secrets profile a new relay's named token key is read
    from.
    """
    return relay_definitions_document(
        relay_service=relay_service, settings=settings, path=path
    )


def relay_reconciliation(
    *,
    port_allocator: RelayPortAllocator,
    session_factory: Any,
    schedule: RelayReconciliationSchedule,
) -> ComputeProvisioningBackgroundTask:
    """The backstop beneath the release effect: a periodic sweep returning
    leases whose reservation was released by a path that bypassed it."""
    is_owner_released = fulfillment_lease_owner_is_released(session_factory)
    return ComputeProvisioningBackgroundTask(
        "relay-port-reconciliation",
        lambda: port_allocator.run_reconciliation(
            is_owner_released=is_owner_released,
            poll_interval_seconds=schedule.poll_interval_seconds,
            grace=timedelta(seconds=schedule.grace_seconds),
        ),
        "Relay port reconciliation started (interval=%ds grace=%ds)",
        (int(schedule.poll_interval_seconds), int(schedule.grace_seconds)),
    )


def relay_contribution(
    *,
    session_factory: Any,
    settings: Any,
    relay_service: RelayService,
    port_allocator: RelayPortAllocator,
    definitions_path: Path | None,
    reconciliation: RelayReconciliationSchedule | None,
) -> ExecutorAdapterBundle:
    """The relays' contribution: no executor or provider of their own, only
    the release effect, the definitions document, and, unless
    ``reconciliation`` is None, the reconciliation worker."""
    return ExecutorAdapterBundle(
        name=RELAY_CONTRIBUTION,
        executors=(),
        release_effects=(release_reservation_ports,),
        definition_documents=(
            relay_definitions(
                relay_service=relay_service, settings=settings, path=definitions_path
            ),
        ),
        background_tasks=()
        if reconciliation is None
        else (
            relay_reconciliation(
                port_allocator=port_allocator,
                session_factory=session_factory,
                schedule=reconciliation,
            ),
        ),
    )


__all__ = [
    "RELAY_CONTRIBUTION",
    "RelayReconciliationSchedule",
    "relay_contribution",
    "relay_definitions",
    "relay_reconciliation",
]
