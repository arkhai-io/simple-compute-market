"""The compute family's relays: rendezvous points, their port leases, and the
rules that keep a delivered connection string valid for a lease's life.

A relay is a tunnel rendezvous any family host dials; every domain whose
deliveries reach their buyer through one leases ports from its one window
through one allocator. See
``openspec/specs/physical-provisioning/spec.md#requirement-relays-are-administered-resources``.
"""

from .allocator import (
    DEFAULT_GRANT_EXPIRY_GRACE,
    DEFAULT_PORT_REUSE_MARGIN,
    FULFILLMENT_OWNER_KIND,
    PortLease,
    RelayPortAllocator,
    RelayWindowExhaustedError,
    fulfillment_lease_owner_is_released,
    grant_expiry,
    release_reservation_ports,
    reservation_lease_end,
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
from .grants import GRANT_TYPE, epoch_seconds, grant_claims, sign_compact, sign_grant
from .keys import GrantKey, GrantKeyError, public_key_text, thumbprint
from .rebinding import (
    ManagementRouteRefused,
    RelayRebindingRefused,
    check_host_pool_change,
    check_management_route,
    check_pool_relay_change,
    check_relay_endpoint_change,
    check_relay_token_rotation,
    pool_relay_id,
    relay_host_connection_change_hooks,
    relay_host_pool_change_hooks,
)
from .pool_relays import (
    RELAY_ID_FIELD,
    check_relay_usable,
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
from .variables import (
    RELAY_ADMIN_PASSWORD_VARIABLE,
    RELAY_JOB_RESERVED_VARIABLES,
    RELAY_GRANT_VARIABLE,
    RELAY_SECRET_VARIABLES,
    RELAY_TOKEN_VARIABLE,
)

__all__ = [
    "ActiveGrantKeyView",
    "DEFAULT_GRANT_EXPIRY_GRACE",
    "DEFAULT_PORT_REUSE_MARGIN",
    "FULFILLMENT_OWNER_KIND",
    "GRANT_TYPE",
    "GrantKey",
    "GrantKeyError",
    "GrantKeysView",
    "ManagementRouteRefused",
    "PoolRelay",
    "PortLease",
    "RELAY_ADMIN_PASSWORD_VARIABLE",
    "RELAY_JOB_RESERVED_VARIABLES",
    "RELAY_GRANT_VARIABLE",
    "RELAY_ID_FIELD",
    "RELAY_CONTRIBUTION",
    "RELAY_DOCUMENT_KIND",
    "RELAY_SECRET_VARIABLES",
    "RELAY_TOKEN_VARIABLE",
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
    "check_management_route",
    "check_pool_relay_change",
    "check_relay_endpoint_change",
    "check_relay_token_rotation",
    "check_relay_usable",
    "epoch_seconds",
    "fulfillment_lease_owner_is_released",
    "grant_claims",
    "grant_expiry",
    "import_relay_definitions",
    "import_relay_definitions_in_session",
    "parse_relay_definitions",
    "pool_relay_id",
    "public_key_text",
    "relay_contribution",
    "relay_definitions_document",
    "relay_execution_fields",
    "relay_host_connection_change_hooks",
    "relay_host_pool_change_hooks",
    "release_reservation_ports",
    "reservation_lease_end",
    "set_pool_relay",
    "sign_compact",
    "sign_grant",
    "thumbprint",
    "validate_relay_reference",
]
