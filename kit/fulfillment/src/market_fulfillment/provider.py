"""Domain-neutral fulfillment lifecycle contracts."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, TYPE_CHECKING, TypeAlias
if TYPE_CHECKING:
    from .settlement_types import PhysicalSettlementRequest, SettlementResource

class ProviderOperationState(str, Enum):
    pending='pending'; succeeded='succeeded'; failed='failed'; unknown='unknown'

@dataclass(frozen=True)
class FulfillmentResult:
    provider_metadata: dict[str, Any]

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
    async def create(self, request:'PhysicalSettlementRequest', resource:'SettlementResource')->FulfillmentResult: ...
    @abstractmethod
    async def teardown(self, capacity_reservation_id:str, resource:'SettlementResource', provider_metadata:dict[str,Any])->FulfillmentResult: ...
    @abstractmethod
    async def get_status(self, capacity_reservation_id:str, resource:'SettlementResource', provider_metadata:dict[str,Any])->ProviderStatus: ...

class FulfillmentError(Exception): pass
class ProviderNotFoundError(FulfillmentError): pass
class ProviderUnavailableError(FulfillmentError): pass
class ProviderConfigInvalidError(FulfillmentError): pass
class FulfillmentConflictError(FulfillmentError): pass
class FulfillmentCreateFailedError(FulfillmentError): pass
class FulfillmentStatusFailedError(FulfillmentError): pass
class FulfillmentTeardownFailedError(FulfillmentError): pass
class FulfillmentRequestInvalidError(FulfillmentError): pass

ProviderRegistrationKey: TypeAlias = str | tuple[str, str]


class ProviderRegistry:
    """Resolve domain providers by infrastructure mechanism and resource kind.

    Provider-only registrations remain as an explicit compatibility fallback.
    A scoped registration is never inferred for a provider-only lookup or for a
    different resource kind.
    """

    def __init__(
        self,
        providers: dict[ProviderRegistrationKey, FulfillmentProvider],
    ) -> None:
        self._providers = dict(providers)

    def require(
        self,
        provider: str,
        resource_kind: str | None = None,
    ) -> FulfillmentProvider:
        if resource_kind is not None:
            scoped = self._providers.get((provider, resource_kind))
            if scoped is not None:
                return scoped
        legacy = self._providers.get(provider)
        if legacy is not None:
            return legacy
        scope = (
            f", resource_kind={resource_kind!r}"
            if resource_kind is not None
            else ""
        )
        raise ProviderNotFoundError(
            "No FulfillmentProvider registered for "
            f"provider={provider!r}{scope}"
        )
