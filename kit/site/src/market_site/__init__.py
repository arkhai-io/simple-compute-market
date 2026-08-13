"""Site-authority scaffold: capacity ledger, tables, and HTTP surface.

The shared half of a site-authority service
(docs/development/ARCHITECTURE.md, "Capacity and the Site Authority"):
the unit-counted resource ledger, reservation holds with their lease
tail, the anonymous versioned capacity-event feed, and the
``/capacity`` router mirroring the ``SiteCapacityAuthority`` contract. A
hosting service (the VM provisioning service; the API-credits service)
mounts the tables on its engine and the router on its app.
"""

from .authority import (  # noqa: F401
    LedgerSiteAuthority,
    SiteAuthorityLedger,
    SiteAuthorityPort,
)
from .db import (  # noqa: F401
    HELD_RESERVATION_STATES,
    ReservationState,
    Base,
    CapacityEvent,
    CapacityReservation,
)
from .ledger import (  # noqa: F401
    CapacityConflictError,
    CapacityLedgerService,
    dict_resource_satisfies_claim,
    parse_utc,
    ResourceFeasibilityView,
    resource_feasibility_view,
    resource_satisfies_requirement,
    SettlementAbandonmentHook,
)
from .router import make_capacity_router  # noqa: F401
