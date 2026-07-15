"""
A ``FulfillmentProvider`` executes create/status/teardown operations
against an already-selected ``SettlementResource``. It never selects or
substitutes a resource itself — that is ``PhysicalSettlementScheduler``'s
job, entirely outside this module.

This layer is stateless and provider-agnostic: it has no identity map of
its own, so ``resource``/``provider_metadata`` are explicit parameters on
every method. ``FulfillmentService`` (a different, stateful layer — see
``fulfillment_service.py``) owns the allocation-to-fulfillment identity and
has simplified signatures; this module does not.

See openspec/changes/pools-3-fulfillment-provider/design.md for the full
design discussion.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from compute_provisioning import PhysicalSettlementRequest, SettlementResource


class ProviderOperationState(str, Enum):
    """Normalized state of one dispatched provider operation.

    Describes whether the last accepted create/teardown operation has
    finished — not ongoing resource health or liveness. A provider that
    reports "succeeded" is not asserting the resource is still running
    right now, only that the dispatched operation completed successfully.
    """

    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    unknown = "unknown"


@dataclass(frozen=True)
class FulfillmentResult:
    """Result of accepting an asynchronous provider dispatch.

    Returned the moment work is *submitted*, not when it finishes.
    """

    provider_metadata: dict[str, Any]


@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderOperationState
    detail: str | None = None


class FulfillmentProvider(ABC):
    """Minimum contract for any physical settlement provider.

    ``create``/``teardown`` are dispatch-only: they submit underlying work
    and return once it is accepted, without blocking until it reaches a
    terminal state. ``get_status`` is how completion is subsequently
    observed.

    A provider may validate that the selected resource is usable, but MUST
    NOT select or substitute a different resource. Placement remains
    solely the scheduler's responsibility.
    """

    @abstractmethod
    async def create(
        self,
        request: "PhysicalSettlementRequest",
        resource: "SettlementResource",
    ) -> FulfillmentResult: ...

    @abstractmethod
    async def teardown(
        self,
        allocation_id: str,
        resource: "SettlementResource",
        provider_metadata: dict[str, Any],
    ) -> FulfillmentResult: ...

    @abstractmethod
    async def get_status(
        self,
        allocation_id: str,
        resource: "SettlementResource",
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus: ...


# ---------------------------------------------------------------------------
# Error taxonomy.
# ---------------------------------------------------------------------------


class FulfillmentError(Exception):
    """Base error for this change's fulfillment-provider/service failures."""


class ProviderNotFoundError(FulfillmentError):
    """No FulfillmentProvider is registered for the requested provider string."""


class ProviderUnavailableError(FulfillmentError):
    """A registered provider could not be reached or is not operational."""


class ProviderConfigInvalidError(FulfillmentError):
    """Pool provider configuration could not be resolved or is invalid.

    Covers: the resource's pool no longer exists, its provider_config fails
    validation, or a snapshotted extra-var collides with a built-in job
    variable.
    """


class FulfillmentConflictError(FulfillmentError):
    """A create request reuses allocation_id with non-equivalent identity.

    Raised by FulfillmentService before any provider operation is
    dispatched — see design.md Decision 4 for the exact equivalence
    definition.
    """


class FulfillmentCreateFailedError(FulfillmentError):
    """The provider could not accept/submit a create operation."""


class FulfillmentStatusFailedError(FulfillmentError):
    """Status could not be determined due to an unexpected error.

    Distinct from ProviderStatus(state=unknown): that's the normal,
    expected outcome when a job is missing or unreadable (LookupError).
    This error is for anything else — it must not be silently folded into
    "unknown".
    """


class FulfillmentTeardownFailedError(FulfillmentError):
    """The provider could not accept/submit a teardown operation."""
