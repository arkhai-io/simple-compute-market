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
from .db import PoolRelay, Relay, RelayPortLease, RelayRetiredGrantKey
from .definitions import (
    RELAY_DOCUMENT_KIND,
    RelayDefinitionError,
    import_relay_definitions,
    import_relay_definitions_in_session,
    parse_relay_definitions,
    relay_definitions_document,
)
from .execution import RelayExecutionResolver, RelayUnusableAtExecutionError
from .keys import GrantKey, GrantKeyError, public_key_text, thumbprint
from .rebinding import (
    RELAY_HOST_POOL_CHANGE_HOOKS,
    RelayRebindingRefused,
    check_host_pool_change,
    check_pool_relay_change,
    check_relay_endpoint_change,
    check_relay_token_rotation,
    pool_relay_id,
)
from .pool_relays import (
    RELAY_ID_FIELD,
    relay_execution_fields,
    set_pool_relay,
    validate_relay_reference,
)
from .route_service import RelayRouteService
from .service import (
    UNSET,
    ActiveGrantKeyView,
    GrantKeysView,
    RelayEndpointConflictError,
    RelayGrantKeyNotStagedError,
    RelayNotFoundError,
    RelayService,
    RelayValidationError,
    RelayView,
    RetiredGrantKeyView,
    StagedGrantKeyView,
)

__all__ = [
    "ActiveGrantKeyView",
    "FULFILLMENT_OWNER_KIND",
    "GrantKey",
    "GrantKeyError",
    "GrantKeysView",
    "PoolRelay",
    "PortLease",
    "RELAY_ID_FIELD",
    "RELAY_CONTRIBUTION",
    "RELAY_DOCUMENT_KIND",
    "RELAY_HOST_POOL_CHANGE_HOOKS",
    "Relay",
    "RelayDefinitionError",
    "RelayEndpointConflictError",
    "RelayExecutionResolver",
    "RelayGrantKeyNotStagedError",
    "RelayNotFoundError",
    "RelayPortAllocator",
    "RelayPortLease",
    "RelayRebindingRefused",
    "RelayReconciliationSchedule",
    "RelayRetiredGrantKey",
    "RelayRouteService",
    "RelayService",
    "RelayUnusableAtExecutionError",
    "RelayValidationError",
    "RelayView",
    "RelayWindowExhaustedError",
    "RetiredGrantKeyView",
    "StagedGrantKeyView",
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
    "public_key_text",
    "relay_contribution",
    "relay_definitions_document",
    "relay_execution_fields",
    "release_reservation_ports",
    "set_pool_relay",
    "thumbprint",
    "validate_relay_reference",
]
