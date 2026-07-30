"""Domain-neutral fulfillment lifecycle contracts."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, TYPE_CHECKING
from .envelopes import VersionedEnvelope
if TYPE_CHECKING:
    from .settlement_types import SettlementResource

class ProviderOperationState(str, Enum):
    pending='pending'; succeeded='succeeded'; failed='failed'; unknown='unknown'

@dataclass(frozen=True)
class FulfillmentResult:
    provider_metadata: dict[str, Any]

@dataclass(frozen=True)
class SettlementResult:
    capacity_reservation_id: str
    fulfillment_id: str
    resource: 'SettlementResource'
    provisioned_resources: tuple[dict[str, Any], ...]
    provider_metadata: dict[str, Any]

@dataclass(frozen=True)
class ProvisionedResourceDescriptor:
    provisioned_resource_id: str
    status: str

@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderOperationState
    detail: str | None = None

@dataclass(frozen=True)
class FulfillmentValidationIssue:
    code: str
    message: str
    field: str | None = None

@dataclass(frozen=True)
class FulfillmentValidationResult:
    issues: tuple[FulfillmentValidationIssue, ...] = ()
    @property
    def valid(self) -> bool:
        return not self.issues

class FulfillmentProvider(ABC):
    @abstractmethod
    def prepare_create(self, *, capacity_reservation_id:str, request: VersionedEnvelope[Any], resource:'SettlementResource', pool_config:dict[str,Any]) -> VersionedEnvelope[Any]: ...
    @abstractmethod
    async def dispatch_create(self, prepared:VersionedEnvelope[Any]) -> FulfillmentResult: ...
    @abstractmethod
    def prepare_teardown(self, settlement_result:SettlementResult, pool_config:dict[str,Any]) -> VersionedEnvelope[Any]: ...
    @abstractmethod
    async def dispatch_teardown(self, prepared:VersionedEnvelope[Any]) -> FulfillmentResult: ...
    @abstractmethod
    def resolve_provisioned_resources(self, provider_metadata:dict[str,Any]) -> tuple[str, ...]:
        """Return domain resource references for a confirmed-successful create.

        Pure and synchronous -- no I/O. Called by create-status convergence
        exactly once, only after ``get_status`` reports ``succeeded``, never
        earlier: a ``ProvisionedResource`` row must never represent a
        resource whose creation might still fail. Decodes whatever
        adapter-owned metadata shape this provider persisted at dispatch
        acknowledgement time; shared orchestration does not interpret the
        contents, only the returned tuple of opaque reference strings.
        """
        ...
    @abstractmethod
    async def get_status(self, capacity_reservation_id:str, resource:'SettlementResource', provider_metadata:dict[str,Any])->ProviderStatus: ...
    @abstractmethod
    async def fetch_credentials(
        self,
        provider_metadata: dict[str, Any],
        provisioned_resources: tuple[ProvisionedResourceDescriptor, ...],
    ) -> VersionedEnvelope[Any]:
        """Return a fresh versioned domain result for an active fulfillment.

        The fulfillment kit supplies only its opaque output identities and
        statuses via ``provisioned_resources``; the adapter owns the nested
        payload schema and any many-to-many credential-to-output
        associations it wants to express within it.

        Async, since it performs provider I/O -- unlike
        ``resolve_provisioned_resources``, which is pure and synchronous.
        Called only when the aggregate is ``active``, directly by
        ``get_fulfillment_result``, with no claim, lease, or generation
        bookkeeping: this is a stateless read, never a coordinated mutation,
        and this codebase has no credential-rotation source for a generation
        counter to track. Raise ``CredentialFetchFailedError`` on any
        expected fetch failure (missing/invalid metadata, an unresolvable
        credential store) so shared orchestration can distinguish it from a
        workload failure and let the caller retry the read; an unexpected
        exception is wrapped into the same category by the orchestration
        boundary rather than leaking raw provider internals to the caller.
        """
        ...

class FulfillmentError(Exception): pass
class ProviderNotFoundError(FulfillmentError): pass
class ProviderUnavailableError(FulfillmentError): pass
class ProviderConfigInvalidError(FulfillmentError): pass
class FulfillmentConflictError(FulfillmentError): pass
class FulfillmentCreateFailedError(FulfillmentError): pass
class FulfillmentStatusFailedError(FulfillmentError): pass
class FulfillmentTeardownFailedError(FulfillmentError): pass
class FulfillmentRequestInvalidError(FulfillmentError): pass
class CredentialFetchFailedError(FulfillmentError): pass

class ProviderRegistry:
    def __init__(self, providers:dict[str,FulfillmentProvider]): self._providers=dict(providers)
    def require(self, provider:str)->FulfillmentProvider:
        try: return self._providers[provider]
        except KeyError: raise ProviderNotFoundError(f"No FulfillmentProvider registered for provider={provider!r}") from None
