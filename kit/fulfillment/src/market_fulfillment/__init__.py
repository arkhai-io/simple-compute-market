"""Domain-neutral settlement-resource scheduling and fulfillment contracts.

The package sits above the site and resource-pool authority kits so those
lower layers remain independent of provider execution. Domain adapters own
provider-specific translation and infrastructure behavior.

See ``openspec/specs/fulfillment/spec.md``.
"""

from .envelopes import VersionedEnvelope, envelope
from .ids import (
    new_capacity_reservation_id,
    new_fulfillment_id,
    new_provisioned_resource_id,
    new_result_id,
    new_settlement_resource_id,
)
from .provider import (
    FulfillmentConflictError,
    FulfillmentCreateFailedError,
    FulfillmentError,
    FulfillmentProvider,
    FulfillmentRequestInvalidError,
    FulfillmentResult,
    FulfillmentStatusFailedError,
    FulfillmentTeardownFailedError,
    FulfillmentValidationIssue,
    FulfillmentValidationResult,
    ProviderConfigInvalidError,
    ProviderNotFoundError,
    ProviderOperationState,
    ProviderRegistry,
    ProviderStatus,
    ProviderUnavailableError,
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
    "FulfillmentConflictError",
    "FulfillmentCreateFailedError",
    "FulfillmentError",
    "FulfillmentProvider",
    "FulfillmentRequestInvalidError",
    "FulfillmentResult",
    "FulfillmentStatusFailedError",
    "FulfillmentTeardownFailedError",
    "FulfillmentValidationIssue",
    "FulfillmentValidationResult",
    "ProviderConfigInvalidError",
    "ProviderNotFoundError",
    "ProviderOperationState",
    "ProviderRegistry",
    "ProviderStatus",
    "ProviderUnavailableError",
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
