"""Executor adapter registration for opaque, domain-validated action payloads."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import CredentialEnvelope, ExecutorActionEnvelope, ResultEnvelope


class UnsupportedExecutorActionError(LookupError):
    """No registered adapter supports an executor/action pair."""


class ExecutorMismatchError(ValueError):
    """The requested executor does not own the committed reservation."""


class ExecutorAdapter(Protocol):
    executor_kind: str

    def validate_parameters(self, action_kind: str, parameters: Mapping[str, Any]) -> Any:
        """Validate opaque command parameters and return the adapter-owned value."""

    async def submit(
        self, envelope: ExecutorActionEnvelope, validated_parameters: Any
    ) -> str:
        """Submit executor work and return its durable job identifier."""

    def validate_result(self, action_kind: str, result: Mapping[str, Any]) -> ResultEnvelope:
        """Validate and classify an executor-owned terminal result."""

    def validate_credentials(
        self, action_kind: str, credentials: list[Mapping[str, Any]]
    ) -> list[CredentialEnvelope]:
        """Validate and classify executor-owned credentials."""


@dataclass(frozen=True)
class FunctionalExecutorAdapter:
    """Small adapter implementation assembled from domain-owned callables."""

    executor_kind: str
    parameter_validators: Mapping[str, Callable[[Mapping[str, Any]], Any]]
    submit_action: Callable[[ExecutorActionEnvelope, Any], Awaitable[str]]
    result_validators: Mapping[str, Callable[[Mapping[str, Any]], ResultEnvelope]]
    credential_validators: Mapping[
        str, Callable[[list[Mapping[str, Any]]], list[CredentialEnvelope]]
    ]

    def validate_parameters(self, action_kind: str, parameters: Mapping[str, Any]) -> Any:
        try:
            validator = self.parameter_validators[action_kind]
        except KeyError as exc:
            raise UnsupportedExecutorActionError(
                f"executor {self.executor_kind!r} does not support action {action_kind!r}"
            ) from exc
        return validator(parameters)

    async def submit(
        self, envelope: ExecutorActionEnvelope, validated_parameters: Any
    ) -> str:
        return await self.submit_action(envelope, validated_parameters)

    def validate_result(self, action_kind: str, result: Mapping[str, Any]) -> ResultEnvelope:
        try:
            return self.result_validators[action_kind](result)
        except KeyError as exc:
            raise UnsupportedExecutorActionError(
                f"executor {self.executor_kind!r} has no result codec for {action_kind!r}"
            ) from exc

    def validate_credentials(
        self, action_kind: str, credentials: list[Mapping[str, Any]]
    ) -> list[CredentialEnvelope]:
        validator = self.credential_validators.get(action_kind)
        return validator(credentials) if validator is not None else []


class ExecutorAdapterRegistry:
    """Select adapters strictly by declared executor identity."""

    def __init__(self, adapters: list[ExecutorAdapter] | tuple[ExecutorAdapter, ...] = ()) -> None:
        self._adapters: dict[str, ExecutorAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ExecutorAdapter) -> None:
        if adapter.executor_kind in self._adapters:
            raise ValueError(f"duplicate executor adapter: {adapter.executor_kind}")
        self._adapters[adapter.executor_kind] = adapter

    def get(self, executor_kind: str) -> ExecutorAdapter:
        try:
            return self._adapters[executor_kind]
        except KeyError as exc:
            raise UnsupportedExecutorActionError(
                f"unsupported executor kind: {executor_kind!r}"
            ) from exc
