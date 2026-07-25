"""Domain-neutral settlement-resource scheduling and fulfillment contracts.

The package sits above the site and resource-pool authority kits so those
lower layers remain independent of provider execution. Domain adapters own
provider-specific translation and infrastructure behavior.

See ``openspec/specs/fulfillment/spec.md``.
"""

from .backoff import Backoff
from .backfill import (
    LegacyBackfillValidationError,
    LegacyFulfillmentBackfillDraft,
)
from .db import (
    Base as FulfillmentBase,
    ProvisionedResource,
    SchedulingCursor,
    SettlementRecord,
    SettlementRecordState,
)
from .envelopes import VersionedEnvelope, envelope
from .ids import (
    new_capacity_reservation_id,
    new_fulfillment_id,
    new_provisioned_resource_id,
    new_result_id,
    new_settlement_resource_id,
)
from .recovery_diagnostics import RecoveryDiagnostics, RecoveryStateDiagnostics
from .results import (
    FULFILLMENT_RESULT_KIND,
    FULFILLMENT_RESULT_SCHEMA_VERSION,
    FulfillmentResultPayload,
    ProvisionedResourceOutput,
    build_fulfillment_result_envelope,
)
from .provider import (
    CredentialFetchFailedError,
    FulfillmentConflictError,
    FulfillmentCreateFailedError,
    FulfillmentError,
    FulfillmentProvider,
    FulfillmentRequestInvalidError,
    FulfillmentResult,
    SettlementResult,
    FulfillmentStatusFailedError,
    FulfillmentTeardownFailedError,
    FulfillmentValidationIssue,
    FulfillmentValidationResult,
    ProviderConfigInvalidError,
    ProviderNotFoundError,
    ProviderOperationState,
    ProviderRegistry,
    ProviderStatus,
    ProvisionedResourceDescriptor,
    ProviderUnavailableError,
)
from .settlement_repository import SettlementRepository, begin_sqlite_write_transaction
from .fulfillment import FulfillmentAcceptance, FulfillmentOrchestrator, FulfillmentStatus
from .fulfillment_persistence import (
    FulfillmentAcceptanceDecision, FulfillmentTransaction, FulfillmentUnitOfWork,
    SqlAlchemyFulfillmentTransaction, SqlAlchemyFulfillmentUnitOfWork,
)
from .round_robin_policy import DeterministicRoundRobinPolicy
from .scheduler import MissingResourceKindError, PhysicalSettlementScheduler
from .scheduling_persistence import (
    SchedulingTransaction,
    SchedulingUnitOfWork,
    SqlAlchemySchedulingTransaction,
    SqlAlchemySchedulingUnitOfWork,
)
from .scheduling import SchedulingCursorState, SettlementSchedulingPolicy
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
from .transitions import InvalidSettlementTransitionError, validate_transition

__all__ = [
    "Backoff",
    "CapacityReservationExpiredError",
    "begin_sqlite_write_transaction",
    "FulfillmentBase",
    "SqlAlchemyFulfillmentUnitOfWork",
    "SqlAlchemyFulfillmentTransaction",
    "FulfillmentUnitOfWork",
    "FulfillmentTransaction",
    "FulfillmentAcceptanceDecision",
    "FulfillmentOrchestrator",
    "FulfillmentAcceptance",
    "FulfillmentStatus",
    "CredentialFetchFailedError",
    "FulfillmentConflictError",
    "FulfillmentCreateFailedError",
    "FulfillmentError",
    "FulfillmentProvider",
    "FulfillmentRequestInvalidError",
    "FulfillmentResult",
    "FulfillmentResultPayload",
    "FulfillmentStatusFailedError",
    "FulfillmentTeardownFailedError",
    "FulfillmentValidationIssue",
    "FulfillmentValidationResult",
    "FULFILLMENT_RESULT_KIND",
    "FULFILLMENT_RESULT_SCHEMA_VERSION",
    "InvalidSettlementTransitionError",
    "LegacyBackfillValidationError",
    "LegacyFulfillmentBackfillDraft",
    "ProviderConfigInvalidError",
    "ProviderNotFoundError",
    "ProviderOperationState",
    "ProviderRegistry",
    "ProviderStatus",
    "ProviderUnavailableError",
    "ProvisionedResourceDescriptor",
    "ProvisionedResourceOutput",
    "RecoveryDiagnostics",
    "RecoveryStateDiagnostics",
    "ProvisionedResource",
    "DeterministicRoundRobinPolicy",
    "MissingResourceKindError",
    "NoEligibleSettlementResourceError",
    "PhysicalSettlementError",
    "PhysicalSettlementRequest",
    "PhysicalSettlementScheduler",
    "SchedulingCursor",
    "SchedulingCursorState",
    "SchedulingTransaction",
    "SchedulingUnitOfWork",
    "SqlAlchemySchedulingTransaction",
    "SqlAlchemySchedulingUnitOfWork",
    "SettlementCandidate",
    "SettlementEntityNotFoundError",
    "SettlementRecord",
    "SettlementRecordState",
    "SettlementResult",
    "SettlementRepository",
    "SettlementRequestMismatchError",
    "SettlementRequirement",
    "SettlementResource",
    "SettlementSchedulingPolicy",
    "VersionedEnvelope",
    "build_fulfillment_result_envelope",
    "envelope",
    "new_capacity_reservation_id",
    "new_fulfillment_id",
    "new_provisioned_resource_id",
    "new_result_id",
    "new_settlement_resource_id",
    "validate_transition",
]
