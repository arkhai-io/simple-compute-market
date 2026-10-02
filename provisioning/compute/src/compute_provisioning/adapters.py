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
    offering_mode: str

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

    offering_mode: str
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
                f"executor {self.offering_mode!r} does not support action {action_kind!r}"
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
                f"executor {self.offering_mode!r} has no result codec for {action_kind!r}"
            ) from exc

    def validate_credentials(
        self, action_kind: str, credentials: list[Mapping[str, Any]]
    ) -> list[CredentialEnvelope]:
        validator = self.credential_validators.get(action_kind)
        return validator(credentials) if validator is not None else []


class ExecutorAdapterRegistry:
    """Select adapters strictly by declared offering mode.

    The adapter is chosen by the mode it serves, not by an identity of its
    own; `executor` here names the dispatch abstraction, never the mode.
    """

    def __init__(self, adapters: list[ExecutorAdapter] | tuple[ExecutorAdapter, ...] = ()) -> None:
        self._adapters: dict[str, ExecutorAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ExecutorAdapter) -> None:
        if adapter.offering_mode in self._adapters:
            raise ValueError(f"duplicate executor adapter: {adapter.offering_mode}")
        self._adapters[adapter.offering_mode] = adapter

    def get(self, offering_mode: str) -> ExecutorAdapter:
        try:
            return self._adapters[offering_mode]
        except KeyError as exc:
            raise UnsupportedExecutorActionError(
                f"unsupported offering mode: {offering_mode!r}"
            ) from exc


@dataclass(frozen=True)
class JobExecution:
    """What runs one executor action: the runner and the playbook it runs.

    ``runner`` is opaque here; the job service that persists the job defines the
    interface it calls. ``playbook_path`` is the runner's default playbook for the
    action, used when the job itself names none.
    """

    runner: Any
    playbook_path: Any = None


class JobExecutorResolver(Protocol):
    def resolve(self, offering_mode: str, action: str) -> JobExecution:
        """Return what runs ``action`` for ``offering_mode``, or raise
        ``UnsupportedExecutorActionError``."""


class JobExecutorTable:
    """The job executors adapter bundles contribute, keyed by offering mode and action.

    Service composition fills the table once and freezes it before the service
    accepts traffic; a job service holds the table from construction and resolves
    through it at execution time. A key registered twice is a composition error,
    and nothing resolves until the table is frozen, so a job can never run against
    a partially composed set of executors.
    """

    def __init__(self) -> None:
        self._executions: dict[tuple[str, str], JobExecution] = {}
        self._frozen = False

    def register(self, offering_mode: str, action: str, execution: JobExecution) -> None:
        if self._frozen:
            raise RuntimeError("job executor table is frozen")
        key = (offering_mode, action)
        if key in self._executions:
            raise ValueError(
                f"duplicate job executor for {offering_mode!r}/{action!r}"
            )
        self._executions[key] = execution

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def resolve(self, offering_mode: str, action: str) -> JobExecution:
        if not self._frozen:
            raise RuntimeError("job executor table has not been composed")
        try:
            return self._executions[(offering_mode, action)]
        except KeyError as exc:
            raise UnsupportedExecutorActionError(
                f"no job executor for offering mode {offering_mode!r} "
                f"and action {action!r}"
            ) from exc

    def executor_modes(self) -> dict[str, str]:
        """``mock`` or ``real`` per offering mode, from the runners it registered.

        A mode is ``mock`` only when every runner registered for it carries the
        compute mock mechanism's rules.
        """
        from .executor_mock import MockRuleSet

        modes: dict[str, str] = {}
        for (offering_mode, _action), execution in self._executions.items():
            is_mock = isinstance(getattr(execution.runner, "rules", None), MockRuleSet)
            current = modes.get(offering_mode)
            modes[offering_mode] = (
                "mock" if is_mock and current in (None, "mock") else "real"
            )
        return modes

    def runners(self) -> tuple[Any, ...]:
        """Each distinct runner once, in registration order."""

        seen: list[Any] = []
        for execution in self._executions.values():
            if not any(execution.runner is runner for runner in seen):
                seen.append(execution.runner)
        return tuple(seen)
