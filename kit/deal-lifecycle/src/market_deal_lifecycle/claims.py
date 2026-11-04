"""Optional interface-owned signed delivery claims, opaque to lifecycle roles."""

from typing import Protocol, runtime_checkable

from market_deal_lifecycle_contracts.models import Rejected
from market_identity import Signer
from pydantic import JsonValue

from .adapters import DeliveryEndIntent, InterfaceRequest


@runtime_checkable
class DeliveryEndClaims(Protocol):
    def sign_delivery_end(self, intent: DeliveryEndIntent, signer: Signer) -> dict[str, JsonValue]: ...
    def verify_delivery_end(self, signed: dict[str, JsonValue], intent: DeliveryEndIntent) -> bool: ...
    def concurrent_request(
        self, intent: DeliveryEndIntent, signed: dict[str, JsonValue] | None,
    ) -> InterfaceRequest | Rejected: ...
