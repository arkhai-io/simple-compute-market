"""Provider-neutral resource-pool administration.

The pool wire models and declaration vocabulary are
``market_resource_pools_contracts``; this package is the authority over them.
"""

from market_resource_pools_contracts.asking_rates import (
    ASKING_RATES_POLICY_TAG,
    asking_rate_entry_problems,
    validate_asking_rates,
)

from .db import DEFAULT_POOL_ID, ResourcePool
from .host_requirement import (
    DeliverableHosts,
    HostRequirement,
    declaration_has_usable_host,
    pool_needs_host,
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
    "DeliverableHosts",
    "declaration_has_usable_host",
    "pool_needs_host",
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
    "ASKING_RATES_POLICY_TAG",
    "asking_rate_entry_problems",
    "validate_asking_rates",
]
