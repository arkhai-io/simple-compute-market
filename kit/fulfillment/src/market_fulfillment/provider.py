"""Domain-neutral fulfillment lifecycle contracts."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, TYPE_CHECKING
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
    #: Whether this provider's delivery connects to a host, declared on the
    #: provider's class. This base class supplies no default: site admission
    #: and settlement scheduling refuse a capacity declaration that names no
    #: host in a pool whose provider needs one, and a defaulted answer would
    #: make that refusal depend on a value nobody chose. A subclass of a
    #: provider that declares it inherits the declaration. Read it through
    #: :func:`provider_needs_host`, which refuses a provider declaring none.
    needs_host: ClassVar[bool]

    @abstractmethod
    def prepare_create(
        self,
        *,
        capacity_reservation_id: str,
        request: VersionedEnvelope[Any],
        resource: "SettlementResource",
        pool_config: dict[str, Any],
        allocate: bool = True,
    ) -> VersionedEnvelope[Any]:
        """Resolve a request into a provider operation, rejecting what it must.

        ``allocate=False`` asks for the same validation with nothing acquired.
        Validation prepares in order to decide whether a request *would* be
        accepted, so a provider that takes a durable or external resource here
        lets a caller who only ever asks consume what it never receives — a
        finite port window drained by repeated validation, for instance.

        A provider that acquires nothing may ignore the flag. One that does
        acquire MUST honour it, and MUST still perform every rejection it
        performs when accepting: purity is about acquiring, not about
        checking, and validation that skips a check stops answering the
        question it exists for.
        """
        ...
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
    def resolve_executor_job_id(
        self, provider_metadata: dict[str, Any]
    ) -> str | None:
        """Return this provider's own handle for the create it dispatched.

        Pure and synchronous. Surfaced onto the capacity reservation so an
        operator holding a lease can reach the execution that produced it --
        the durable fulfillment id is already reachable from settle status and
        the buyer's run-log, whereas a provider's own job handle is visible
        nowhere outside the service that dispatched it, and is the one an
        operator can actually act on.

        Concrete rather than abstract, returning ``None``: a provider with no
        addressable job handle is a legitimate implementation, and forcing
        every existing provider to declare that it has none would be churn
        that says nothing. Shared orchestration does not interpret the value,
        and does not know which metadata key holds it.
        """
        del provider_metadata
        return None

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

def provider_needs_host(provider: Any) -> bool:
    """The provider's declared host need, refusing a provider that declares none.

    Raises ``TypeError`` when ``needs_host`` is absent or not a ``bool``, so a
    composition cannot register a provider whose need it would have to guess.
    """
    declared = getattr(type(provider), "needs_host", None)
    if not isinstance(declared, bool):
        raise TypeError(
            f"fulfillment provider {type(provider).__name__} does not declare "
            "needs_host as a bool"
        )
    return declared

class ProviderRegistry:
    def __init__(self, providers:dict[str,FulfillmentProvider]):
        # Registration is where a provider joins the fleet, so a provider that
        # does not declare whether it needs a host is refused here rather than
        # wherever the answer is first needed.
        for provider in providers.values():
            provider_needs_host(provider)
        self._providers=dict(providers)
    def require(self, provider:str)->FulfillmentProvider:
        try: return self._providers[provider]
        except KeyError: raise ProviderNotFoundError(f"No FulfillmentProvider registered for provider={provider!r}") from None
