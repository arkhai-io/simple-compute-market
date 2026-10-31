"""The compute family's relays: rendezvous points, their port leases, and the
rules that keep a delivered connection string valid for a lease's life.

A relay is a tunnel rendezvous any family host dials; every domain whose
deliveries reach their buyer through one leases ports from its one window
through one allocator. See
``openspec/specs/physical-provisioning/spec.md#requirement-relays-are-administered-resources``.
"""

from .allocator import (
    FULFILLMENT_OWNER_KIND,
    PortLease,
    RelayPortAllocator,
    RelayWindowExhaustedError,
    fulfillment_lease_owner_is_released,
    release_reservation_ports,
)
from .composition import (
    RELAY_CONTRIBUTION,
    RelayReconciliationSchedule,
    relay_contribution,
)
from .db import Relay, RelayPortLease
from .definitions import (
    RELAY_DOCUMENT_KIND,
    RelayDefinitionError,
    import_relay_definitions,
    import_relay_definitions_in_session,
    parse_relay_definitions,
    relay_definitions_document,
)
from .execution import RelayExecutionResolver, RelayUnusableAtExecutionError
from .rebinding import (
    RELAY_HOST_POOL_CHANGE_HOOKS,
    RelayRebindingRefused,
    check_host_pool_change,
    check_pool_relay_change,
    check_relay_endpoint_change,
    check_relay_token_rotation,
    pool_relay_id,
)
from .route_service import RelayRouteService
from .service import (
    UNSET,
    RelayEndpointConflictError,
    RelayNotFoundError,
    RelayService,
    RelayValidationError,
    RelayView,
)

__all__ = [
    "FULFILLMENT_OWNER_KIND",
    "PortLease",
    "RELAY_CONTRIBUTION",
    "RELAY_DOCUMENT_KIND",
    "RELAY_HOST_POOL_CHANGE_HOOKS",
    "Relay",
    "RelayDefinitionError",
    "RelayEndpointConflictError",
    "RelayExecutionResolver",
    "RelayNotFoundError",
    "RelayPortAllocator",
    "RelayPortLease",
    "RelayRebindingRefused",
    "RelayReconciliationSchedule",
    "RelayRouteService",
    "RelayService",
    "RelayUnusableAtExecutionError",
    "RelayValidationError",
    "RelayView",
    "RelayWindowExhaustedError",
    "UNSET",
    "check_host_pool_change",
    "check_pool_relay_change",
    "check_relay_endpoint_change",
    "check_relay_token_rotation",
    "fulfillment_lease_owner_is_released",
    "import_relay_definitions",
    "import_relay_definitions_in_session",
    "parse_relay_definitions",
    "pool_relay_id",
    "relay_contribution",
    "relay_definitions_document",
    "release_reservation_ports",
]
