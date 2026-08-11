"""Ordered failure-action dispatch with domain-owned effects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

FailureActionHandler = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any] | None]]


class FailurePolicyResult(BaseModel):
    context: dict[str, Any]
    actions: list[dict[str, Any]] = Field(default_factory=list)


class FailurePolicy:
    def __init__(
        self,
        actions_provider: Callable[[], Sequence[str] | str | None],
        handlers: Mapping[str, FailureActionHandler],
    ) -> None:
        self._actions_provider = actions_provider
        self._handlers = dict(handlers)

    def configured_actions(self) -> tuple[str, ...]:
        raw = self._actions_provider()
        if raw is None:
            return ()
        values = (raw,) if isinstance(raw, str) else raw
        return tuple(action for item in values if (action := str(item).strip()))

    async def apply(
        self,
        store: Any,
        context: dict[str, Any],
    ) -> FailurePolicyResult:
        stable_context = dict(context)
        outcomes: list[dict[str, Any]] = []
        for action in self.configured_actions():
            handler = self._handlers.get(action)
            if handler is None:
                outcomes.append(
                    {
                        "action": action,
                        "status": "failed",
                        "error": "unknown action",
                    }
                )
                continue
            try:
                result = await handler(store, dict(stable_context))
                if result is None:
                    projected: dict[str, Any] = {
                        "action": action,
                        "status": "succeeded",
                    }
                else:
                    projected = dict(result)
                    projected.setdefault("action", action)
                    status = projected.get("status")
                    if not isinstance(status, str) or not status:
                        raise ValueError(
                            "failure action result must include a non-empty status"
                        )
                outcomes.append(projected)
            except Exception as exc:
                outcomes.append(
                    {
                        "action": action,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
        return FailurePolicyResult(context=stable_context, actions=outcomes)
