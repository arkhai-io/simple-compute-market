"""Reusable startup assembly helpers for provisioning executables."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from core_storefront.app_startup import maybe_await

from .provisioning_lifecycle import cancel_background_tasks, create_background_task


class LoggerLike(Protocol):
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


@dataclass(frozen=True)
class ProvisioningStartupStep:
    """One ordered provisioning startup action."""

    name: str
    action: Callable[[], Any]
    continue_on_error: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class ProvisioningBackgroundTask:
    """A background coroutine scheduled after startup steps complete."""

    name: str
    task_factory: Callable[[], Awaitable[Any]]
    log_message: str | None = None
    log_args: tuple[Any, ...] = ()


@dataclass(frozen=True)
class ProvisioningShutdownStep:
    """One ordered provisioning shutdown action."""

    name: str
    action: Callable[[], Any]
    continue_on_error: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class ProvisioningRuntime:
    """Handles returned by provisioning startup assembly."""

    background_tasks: tuple[Any, ...] = ()


async def run_provisioning_startup_steps(
    steps: Sequence[ProvisioningStartupStep],
    *,
    logger: LoggerLike | None = None,
) -> None:
    """Run provisioning startup steps in order, fail-fast by default."""

    for step in steps:
        try:
            await maybe_await(step.action())
        except Exception as exc:
            if logger is not None and step.error_message:
                logger.error(step.error_message, exc)
            if not step.continue_on_error:
                raise


def start_provisioning_background_task(
    task: ProvisioningBackgroundTask,
    *,
    logger: LoggerLike | None = None,
    create_task: Callable[..., Any] = create_background_task,
) -> Any:
    """Schedule one named background task and emit its startup log message."""

    handle = create_task(task.task_factory(), name=task.name)
    if logger is not None and task.log_message:
        logger.info(task.log_message, *task.log_args)
    return handle


async def start_provisioning_runtime(
    *,
    startup_steps: Sequence[ProvisioningStartupStep] = (),
    background_tasks: Sequence[ProvisioningBackgroundTask]
    | Callable[[], Sequence[ProvisioningBackgroundTask]] = (),
    logger: LoggerLike | None = None,
    create_task: Callable[..., Any] = create_background_task,
) -> ProvisioningRuntime:
    """Run startup steps, then schedule background tasks.

    ``background_tasks`` may be a factory so task specifications can depend on
    services resolved by preceding startup steps.
    """

    await run_provisioning_startup_steps(startup_steps, logger=logger)
    task_specs = background_tasks() if callable(background_tasks) else background_tasks
    handles = tuple(
        start_provisioning_background_task(
            task,
            logger=logger,
            create_task=create_task,
        )
        for task in task_specs
    )
    return ProvisioningRuntime(background_tasks=handles)


async def run_provisioning_shutdown_steps(
    steps: Sequence[ProvisioningShutdownStep],
    *,
    logger: LoggerLike | None = None,
) -> None:
    """Run provisioning shutdown steps in order, fail-fast by default."""

    for step in steps:
        try:
            await maybe_await(step.action())
        except Exception as exc:
            if logger is not None and step.error_message:
                logger.error(step.error_message, exc)
            if not step.continue_on_error:
                raise


async def stop_provisioning_runtime(
    runtime: ProvisioningRuntime,
    *,
    shutdown_steps: Sequence[ProvisioningShutdownStep] = (),
    logger: LoggerLike | None = None,
) -> None:
    """Cancel background tasks and run shutdown steps."""

    await cancel_background_tasks(*runtime.background_tasks)
    await run_provisioning_shutdown_steps(shutdown_steps, logger=logger)
