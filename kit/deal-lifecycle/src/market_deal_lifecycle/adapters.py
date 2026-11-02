"""Injected payment and dispute ports with fail-before-I/O command dispatch.

A payment adapter sends stops only under stated account entries, reverses only
under reverse authority, and never waives notice or releases holds early.
Its local validation refuses unsupported installed-contract capabilities.
A dispute adapter communicates solely with the Agreement's dispute authority;
it never sends payment events or applies a case's effects.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol

from market_deal_lifecycle_contracts.models import (
    AuthorityView, EvidenceItem, Instant, LifecycleCommand, LifecycleOutcome, Reference, Rejected, WireModel,
)
from pydantic import Field, JsonValue, ValidationError

from .delivery import BillingStartResult, DeliveryAuthorization, DeliveryEvidence, DeliveryPhase
from .operations import OperationKeys, OperationStore, remember_command
from .terms import DisputeAuthority


class DeliveryEndIntent(WireModel):
    """Deal intent for either filer, not a payment event or a signed wire claim."""

    kind: Literal["delivery_end"] = "delivery_end"
    ended_at: Instant
    delivered: bool = Field(strict=True)
    cause: Literal["payee", "payer"]


class InterfaceRequest(WireModel):
    interface: Reference
    payload: dict[str, JsonValue]


class PaymentAdapter(Protocol):
    supported_commands: frozenset[str]

    def validate(self, command: LifecycleCommand) -> Rejected | None:
        """Pure validation of parts, stated grants and installed-contract capabilities."""
        ...

    async def submit(self, command: LifecycleCommand, keys: OperationKeys) -> LifecycleOutcome: ...
    async def read(self) -> AuthorityView: ...
    async def authorize(self, phase: DeliveryPhase, evidence: DeliveryEvidence) -> DeliveryAuthorization: ...
    async def start_billing(self, operation_key: str, evidence: DeliveryEvidence) -> BillingStartResult: ...


class DisputeAdapter(Protocol):
    supported_commands: frozenset[str]
    supported_intents: frozenset[str]

    def build_request(self, intent: DeliveryEndIntent) -> InterfaceRequest | Rejected:
        """Map or refuse before I/O; concrete signing belongs to the owning dispute kit."""
        ...

    def build_append(self, case_ref: str, items: list[EvidenceItem]) -> dict[str, JsonValue] | Rejected:
        """Own the interface's evidence packaging and append vocabulary."""
        ...

    def validate_request(self, request: InterfaceRequest) -> Rejected | None: ...
    async def submit(
        self, command: LifecycleCommand, request: InterfaceRequest | None, keys: OperationKeys,
    ) -> LifecycleOutcome: ...
    async def read(self) -> AuthorityView: ...


@dataclass(frozen=True)
class PaymentSelector:
    mechanism: str
    arbiter: str | None = None
    oracle: str | None = None
    oracle_schema: str | None = None


@dataclass(frozen=True)
class PaymentBinding:
    negotiation_id: str
    selector: PaymentSelector


@dataclass(frozen=True)
class DisputeBinding:
    negotiation_id: str
    commitment_ref: str
    authority: DisputeAuthority


class PaymentAdapterTable:
    def __init__(self, entries: Iterable[tuple[PaymentSelector, Callable[[PaymentBinding], PaymentAdapter]]]) -> None:
        copied = {}
        for key, factory in entries:
            if key in copied:
                raise ValueError(f"duplicate payment adapter: {key}")
            copied[key] = factory
        self._entries = MappingProxyType(copied)

    def resolve(self, binding: PaymentBinding) -> PaymentAdapter | None:
        factory = self._entries.get(binding.selector)
        return factory(binding) if factory is not None else None


class DisputeAdapterTable:
    def __init__(self, entries: Iterable[tuple[str, Callable[[DisputeBinding], DisputeAdapter]]]) -> None:
        copied = {}
        for interface, factory in entries:
            if interface in copied:
                raise ValueError(f"duplicate dispute adapter: {interface}")
            copied[interface] = factory
        self._entries = MappingProxyType(copied)

    def resolve(self, binding: DisputeBinding) -> DisputeAdapter | None:
        factory = self._entries.get(binding.authority.interface)
        return factory(binding) if factory is not None else None


async def submit_payment(
    command: LifecycleCommand, binding: PaymentBinding, table: PaymentAdapterTable, store: OperationStore,
) -> LifecycleOutcome:
    if command.negotiation_id != binding.negotiation_id:
        return Rejected(reason="command negotiation does not match payment binding")
    if command.kind in {"dispute", "delivery_end", "append"}:
        return Rejected(reason=f"{command.kind} is not a payment command")
    adapter = table.resolve(binding)
    if adapter is None or command.kind not in adapter.supported_commands:
        return Rejected(reason=f"{binding.selector.mechanism} has no adapter for {command.kind}")
    refusal = adapter.validate(command)
    if refusal is not None:
        return refusal
    keys = await remember_command(command, store)
    if keys is None:
        return Rejected(reason="operation key retry changes content")
    return await adapter.submit(command, keys)


async def submit_dispute(
    command: LifecycleCommand, binding: DisputeBinding, table: DisputeAdapterTable, store: OperationStore,
) -> LifecycleOutcome:
    if command.negotiation_id != binding.negotiation_id:
        return Rejected(reason="command negotiation does not match dispute binding")
    interface = binding.authority.interface
    adapter = table.resolve(binding)
    if adapter is None:
        return Rejected(reason=f"no dispute adapter for {interface}")
    if command.kind not in {"dispute", "delivery_end", "append"} or command.kind not in adapter.supported_commands:
        return Rejected(reason=f"{interface} has no adapter for {command.kind}")
    request = None
    try:
        if command.kind == "delivery_end":
            if "delivery_end" not in adapter.supported_intents:
                return Rejected(reason=f"{interface} has no delivery_end request")
            request = adapter.build_request(DeliveryEndIntent.model_validate(command.payload))
            if isinstance(request, Rejected):
                return request
        elif command.kind == "dispute":
            request = InterfaceRequest.model_validate(command.payload)
        if request is not None:
            if request.interface != interface:
                return Rejected(reason="interface request names another authority interface")
            refusal = adapter.validate_request(request)
            if refusal is not None:
                return refusal
    except (ValidationError, ValueError) as exc:
        return Rejected(reason=f"invalid dispute request: {exc}")
    keys = await remember_command(command, store)
    if keys is None:
        return Rejected(reason="operation key retry changes content")
    return await adapter.submit(command, request, keys)
