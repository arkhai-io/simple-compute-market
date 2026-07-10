"""Reusable ordered startup-step helpers for storefront executables."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class LoggerLike(Protocol):
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


@dataclass(frozen=True)
class StorefrontStartupStep:
    """One ordered startup action.

    ``continue_on_error`` supports non-critical steps such as best-effort remote
    resource syncs. Critical steps keep the default fail-fast behavior.
    """

    name: str
    action: Callable[[], Any]
    continue_on_error: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class StorefrontBackgroundTask:
    """A background coroutine to schedule during startup."""

    name: str
    task_factory: Callable[[], Awaitable[Any]]
    log_message: str | None = None
    log_args: tuple[Any, ...] = ()


async def maybe_await(value: Any) -> Any:
    """Await ``value`` if it is awaitable, otherwise return it unchanged."""

    if inspect.isawaitable(value):
        return await value
    return value


async def run_storefront_startup_steps(
    steps: Sequence[StorefrontStartupStep],
    *,
    logger: LoggerLike | None = None,
) -> None:
    """Run startup steps in order, preserving fail-fast by default."""

    for step in steps:
        try:
            await maybe_await(step.action())
        except Exception as exc:
            if logger is not None and step.error_message:
                logger.error(step.error_message, exc)
            if not step.continue_on_error:
                raise


def start_storefront_background_task(
    task: StorefrontBackgroundTask,
    *,
    logger: LoggerLike | None = None,
    create_task: Callable[[Awaitable[Any]], Any] = asyncio.create_task,
) -> Any:
    """Schedule one background task and emit its startup log message."""

    handle = create_task(task.task_factory())
    if logger is not None and task.log_message:
        logger.info(task.log_message, *task.log_args)
    return handle
