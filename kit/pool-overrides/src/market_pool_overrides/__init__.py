"""Storefront pool overrides as a market-neutral capability.

A storefront's own statement of terms and listing shapes for one pool at one
site, in one offering mode: a durable store, a write checked against the site's
live projection, the one state each stored override is in, the signed-resource
contract, and typed client methods. Each market supplies its vocabulary through
a ``PoolOverrideContribution`` for its offering mode.
"""

from market_pool_overrides.client import (
    PoolOverrideClient,
    SyncPoolOverrideClient,
    pool_override_statuses,
)
from market_pool_overrides.contract import (
    POOL_OVERRIDES_PATH,
    PoolOverrideContract,
    PoolOverrideContractError,
    pool_override_contract,
)
from market_pool_overrides.contribution import PoolOverrideContribution
from market_pool_overrides.records import (
    PoolOverride,
    PoolOverrideAddress,
    PoolOverrideDeleteResponse,
    PoolOverrideListResponse,
    PoolOverrideRecord,
    PoolOverrideResponse,
    PoolOverrideWriteResponse,
    ProjectionGeneration,
    ShapeFeasibility,
)
from market_pool_overrides.service import (
    OVERRIDE_APPLIED,
    OVERRIDE_INACTIVE,
    OVERRIDE_ORPHANED,
    OVERRIDE_SITE_UNCONFIGURED,
    OVERRIDE_UNKNOWN,
    PoolOverrideRefused,
    PoolOverrideService,
    override_state,
)
from market_pool_overrides.store import (
    POOL_OVERRIDES_TABLE,
    SQLitePoolOverrideStore,
    pool_override_migrations,
)

__all__ = [
    "OVERRIDE_APPLIED",
    "OVERRIDE_INACTIVE",
    "OVERRIDE_ORPHANED",
    "OVERRIDE_SITE_UNCONFIGURED",
    "OVERRIDE_UNKNOWN",
    "POOL_OVERRIDES_PATH",
    "POOL_OVERRIDES_TABLE",
    "PoolOverride",
    "PoolOverrideAddress",
    "PoolOverrideClient",
    "PoolOverrideContract",
    "PoolOverrideContractError",
    "PoolOverrideContribution",
    "PoolOverrideDeleteResponse",
    "PoolOverrideListResponse",
    "PoolOverrideRecord",
    "PoolOverrideRefused",
    "PoolOverrideResponse",
    "PoolOverrideService",
    "PoolOverrideWriteResponse",
    "ProjectionGeneration",
    "SQLitePoolOverrideStore",
    "ShapeFeasibility",
    "SyncPoolOverrideClient",
    "override_state",
    "pool_override_contract",
    "pool_override_migrations",
    "pool_override_statuses",
]
