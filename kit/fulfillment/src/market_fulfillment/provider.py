"""Domain-neutral fulfillment lifecycle contracts."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, TYPE_CHECKING
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

class ProviderRegistry:
    def __init__(self, providers:dict[str,FulfillmentProvider]): self._providers=dict(providers)
    def require(self, provider:str)->FulfillmentProvider:
        try: return self._providers[provider]
        except KeyError: raise ProviderNotFoundError(f"No FulfillmentProvider registered for provider={provider!r}") from None
