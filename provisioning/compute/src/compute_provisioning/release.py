"""Executor-neutral release port and kind-based dispatcher."""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ExecutorReleasePort(Protocol):
    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        """Submit release work for an reservation and return its job id."""


class ExecutorReleaseDispatcher:
    """Route release requests by reservation executor kind."""

    def __init__(
        self,
        executors: dict[str, ExecutorReleasePort],
        *,
        default_executor_kind: str | None = None,
    ) -> None:
        self._executors = dict(executors)
        self._default_executor_kind = default_executor_kind

    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        executor_kind = reservation.get("executor_kind") or self._default_executor_kind
        executor = self._executors.get(str(executor_kind)) if executor_kind else None
        if executor is None:
            logger.warning(
                "[LEASE_LIFECYCLE] No release executor registered for executor_kind=%s",
                executor_kind,
            )
            return None
        return await executor.submit_release(reservation)
