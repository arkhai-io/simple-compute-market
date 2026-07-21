"""Domain-neutral physical-settlement scheduling and fulfillment contracts.

See ``docs/development/ARCHITECTURE.md`` and
``openspec/changes/pools-7-storefront-fulfillment-cutover/design.md``
("Shared package boundary") for why this package exists separately from
``kit/resource-pools`` and ``compute_provisioning``.
"""

from .envelopes import VersionedEnvelope, envelope
from .ids import (
    new_capacity_reservation_id,
    new_fulfillment_id,
    new_provisioned_resource_id,
    new_result_id,
    new_settlement_resource_id,
)
from .round_robin_policy import DeterministicRoundRobinPolicy
from .scheduler import MissingResourceKindError, PhysicalSettlementScheduler
from .scheduling import SettlementSchedulingPolicy
from .settlement_types import (
    CapacityReservationExpiredError,
    NoEligibleSettlementResourceError,
    PhysicalSettlementError,
    PhysicalSettlementRequest,
    SettlementCandidate,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
    SettlementRequirement,
    SettlementResource,
)

__all__ = [
    "CapacityReservationExpiredError",
    "DeterministicRoundRobinPolicy",
    "MissingResourceKindError",
    "NoEligibleSettlementResourceError",
    "PhysicalSettlementError",
    "PhysicalSettlementRequest",
    "PhysicalSettlementScheduler",
    "SettlementCandidate",
    "SettlementEntityNotFoundError",
    "SettlementRequestMismatchError",
    "SettlementRequirement",
    "SettlementResource",
    "SettlementSchedulingPolicy",
    "VersionedEnvelope",
    "envelope",
    "new_capacity_reservation_id",
    "new_fulfillment_id",
    "new_provisioned_resource_id",
    "new_result_id",
    "new_settlement_resource_id",
]
