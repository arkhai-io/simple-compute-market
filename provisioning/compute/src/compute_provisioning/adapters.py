"""The job executors domains contribute, resolved by offering mode and action."""

from __future__ import annotations

from typing import Protocol

from .jobs.executor import JobExecutor


class UnsupportedExecutorActionError(LookupError):
    """No job executor is registered for an offering mode and action."""


class JobExecutorResolver(Protocol):
    def resolve(self, offering_mode: str, action: str) -> JobExecutor:
        """Return the executor that runs ``action`` for ``offering_mode``, or
        raise ``UnsupportedExecutorActionError``."""


class JobExecutorTable:
    """The job executors adapter bundles contribute, keyed by offering mode and action.

    Service composition fills the table once and freezes it before the service
    accepts traffic; a job service holds the table from construction and resolves
    through it at execution time. A key registered twice is a composition error,
    and nothing resolves until the table is frozen, so a job can never run against
    a partially composed set of executors.
    """

    def __init__(self) -> None:
        self._executors: dict[tuple[str, str], JobExecutor] = {}
        self._frozen = False

    def register(self, offering_mode: str, action: str, executor: JobExecutor) -> None:
        if self._frozen:
            raise RuntimeError("job executor table is frozen")
        key = (offering_mode, action)
        if key in self._executors:
            raise ValueError(
                f"duplicate job executor for {offering_mode!r}/{action!r}"
            )
        self._executors[key] = executor

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def resolve(self, offering_mode: str, action: str) -> JobExecutor:
        if not self._frozen:
            raise RuntimeError("job executor table has not been composed")
        try:
            return self._executors[(offering_mode, action)]
        except KeyError as exc:
            raise UnsupportedExecutorActionError(
                f"no job executor for offering mode {offering_mode!r} "
                f"and action {action!r}"
            ) from exc

    def executor_modes(self) -> dict[str, str]:
        """``mock`` or ``real`` per offering mode, from the executors it registered.

        A mode is ``mock`` only when every executor registered for it carries the
        compute mock mechanism's rules.
        """
        from .jobs.executor_mock import MockRuleSet

        modes: dict[str, str] = {}
        for (offering_mode, _action), executor in self._executors.items():
            is_mock = isinstance(getattr(executor, "rules", None), MockRuleSet)
            current = modes.get(offering_mode)
            modes[offering_mode] = (
                "mock" if is_mock and current in (None, "mock") else "real"
            )
        return modes

    def executors(self) -> tuple[JobExecutor, ...]:
        """Each distinct executor once, in registration order."""

        seen: list[JobExecutor] = []
        for executor in self._executors.values():
            if not any(executor is known for known in seen):
                seen.append(executor)
        return tuple(seen)
