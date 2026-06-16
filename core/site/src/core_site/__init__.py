"""Site-authority scaffold: capacity ledger, tables, and HTTP surface.

The shared half of a site-authority service
(docs/development/ARCHITECTURE.md, "Capacity and the Site Authority"):
the unit-counted resource ledger, allocation holds with their lease
tail, the anonymous versioned capacity-event feed, and the
``/capacity`` router mirroring the ``CapacityClient`` contract. A
hosting service (the VM provisioning service; the API-tokens service)
mounts the tables on its engine and the router on its app.
"""

from .db import (  # noqa: F401
    HELD_ALLOCATION_STATES,
    AllocationState,
    Base,
    CapacityEvent,
    SiteAllocation,
    SiteResource,
)
from .ledger import (  # noqa: F401
    CapacityConflictError,
    CapacityLedgerService,
    parse_utc,
)
from .router import make_capacity_router  # noqa: F401
