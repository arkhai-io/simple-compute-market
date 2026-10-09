"""Provider-neutral resource-pool administration.

The pool wire models and declaration vocabulary are
``market_resource_pools_contracts``; this package is the authority over them.
"""

from .asking_rates import (
    ACCEPTED_ASKING_RATE_PERIODS,
    ASKING_RATE_SOURCE_HINT,
    ASKING_RATE_SOURCE_NONE,
    ASKING_RATE_SOURCE_OVERRIDE,
    ASKING_RATES_POLICY_TAG,
    AskingRate,
    AskingRateResolution,
    NOT_STATED,
    asking_rate_entry_problems,
    raw_asking_rates,
    resolve_asking_rates,
    validate_asking_rates,
)
from .db import DEFAULT_POOL_ID, ResourcePool
from .host_requirement import HostRequirement, pool_needs_host
from .site_declarations import (
    POOL_ENABLEMENT_UNDECLARED,
    ResolvedPool,
    SiteDeclarations,
    read_site_declarations,
)
from .pool_config_handler import PoolConfigHandler, PoolConfigValidationProblem
from .service import (
    DocumentValidationResult,
    PoolAlreadyExistsError,
    PoolDefinition,
    PoolNotFoundError,
    PoolValidationError,
    ReconciliationPlan,
    ResourcePoolService,
)

__all__ = [
    "DEFAULT_POOL_ID",
    "pool_needs_host",
    "POOL_ENABLEMENT_UNDECLARED",
    "ResolvedPool",
    "SiteDeclarations",
    "read_site_declarations",
    "DocumentValidationResult",
    "HostRequirement",
    "PoolAlreadyExistsError",
    "PoolConfigHandler",
    "PoolConfigValidationProblem",
    "PoolDefinition",
    "PoolNotFoundError",
    "PoolValidationError",
    "ReconciliationPlan",
    "ResourcePool",
    "ResourcePoolService",
    "ACCEPTED_ASKING_RATE_PERIODS",
    "ASKING_RATE_SOURCE_HINT",
    "ASKING_RATE_SOURCE_NONE",
    "ASKING_RATE_SOURCE_OVERRIDE",
    "ASKING_RATES_POLICY_TAG",
    "AskingRate",
    "AskingRateResolution",
    "NOT_STATED",
    "asking_rate_entry_problems",
    "raw_asking_rates",
    "resolve_asking_rates",
    "validate_asking_rates",
]
