"""The job executors domains contribute, resolved by offering mode and action."""

from __future__ import annotations

from typing import Protocol

from .jobs.executor import JobExecutor
from .jobs.executor_mock import executor_is_mocked


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

    def mocked_by_offering_mode(self) -> dict[str, bool]:
        """Whether each offering mode's executors are the mock.

        A mode counts as mocked only when every executor registered for it
        carries the compute mock mechanism's rules (``executor_is_mocked``).
        """
        mocked: dict[str, bool] = {}
        for (offering_mode, _action), executor in self._executors.items():
            mocked[offering_mode] = mocked.get(offering_mode, True) and executor_is_mocked(
                executor
            )
        return mocked

    def executors_by_offering_mode(self) -> dict[str, tuple[JobExecutor, ...]]:
        """Each offering mode's distinct executors, in registration order.

        An implementation reads this to report on the executors it built,
        whichever domain contributed them.
        """
        grouped: dict[str, list[JobExecutor]] = {}
        for (offering_mode, _action), executor in self._executors.items():
            known = grouped.setdefault(offering_mode, [])
            if not any(executor is seen for seen in known):
                known.append(executor)
        return {mode: tuple(executors) for mode, executors in grouped.items()}

    def executors(self) -> tuple[JobExecutor, ...]:
        """Each distinct executor once, in registration order."""

        seen: list[JobExecutor] = []
        for executor in self._executors.values():
            if not any(executor is known for known in seen):
                seen.append(executor)
        return tuple(seen)
