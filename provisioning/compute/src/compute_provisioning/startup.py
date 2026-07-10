"""Reusable startup assembly helpers for compute provisioners."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .lifecycle import cancel_background_tasks, create_background_task


async def maybe_await(value: Any) -> Any:
    """Await awaitables; return plain values unchanged."""

    if hasattr(value, "__await__"):
        return await value
    return value


class LoggerLike(Protocol):
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


@dataclass(frozen=True)
class ComputeProvisioningStartupStep:
    """One ordered compute provisioning startup action."""

    name: str
    action: Callable[[], Any]
    continue_on_error: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class ComputeProvisioningBackgroundTask:
    """A background coroutine scheduled after startup steps complete."""

    name: str
    task_factory: Callable[[], Awaitable[Any]]
    log_message: str | None = None
    log_args: tuple[Any, ...] = ()


@dataclass(frozen=True)
class ComputeProvisioningShutdownStep:
    """One ordered compute provisioning shutdown action."""

    name: str
    action: Callable[[], Any]
    continue_on_error: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class ComputeProvisioningRuntime:
    """Handles returned by compute provisioning startup assembly."""

    background_tasks: tuple[Any, ...] = ()


async def run_compute_provisioning_startup_steps(
    steps: Sequence[ComputeProvisioningStartupStep],
    *,
    logger: LoggerLike | None = None,
) -> None:
    """Run compute provisioning startup steps in order, fail-fast by default."""

    for step in steps:
        try:
            await maybe_await(step.action())
        except Exception as exc:
            if logger is not None and step.error_message:
                logger.error(step.error_message, exc)
            if not step.continue_on_error:
                raise


def start_compute_provisioning_background_task(
    task: ComputeProvisioningBackgroundTask,
    *,
    logger: LoggerLike | None = None,
    create_task: Callable[..., Any] = create_background_task,
) -> Any:
    """Schedule one named background task and emit its startup log message."""

    handle = create_task(task.task_factory(), name=task.name)
    if logger is not None and task.log_message:
        logger.info(task.log_message, *task.log_args)
    return handle


async def start_compute_provisioning_runtime(
    *,
    startup_steps: Sequence[ComputeProvisioningStartupStep] = (),
    background_tasks: Sequence[ComputeProvisioningBackgroundTask]
    | Callable[[], Sequence[ComputeProvisioningBackgroundTask]] = (),
    logger: LoggerLike | None = None,
    create_task: Callable[..., Any] = create_background_task,
) -> ComputeProvisioningRuntime:
    """Run startup steps, then schedule background tasks.

    ``background_tasks`` may be a factory so task specifications can depend on
    services resolved by preceding startup steps.
    """

    await run_compute_provisioning_startup_steps(startup_steps, logger=logger)
    task_specs = background_tasks() if callable(background_tasks) else background_tasks
    handles = tuple(
        start_compute_provisioning_background_task(
            task,
            logger=logger,
            create_task=create_task,
        )
        for task in task_specs
    )
    return ComputeProvisioningRuntime(background_tasks=handles)


async def run_compute_provisioning_shutdown_steps(
    steps: Sequence[ComputeProvisioningShutdownStep],
    *,
    logger: LoggerLike | None = None,
) -> None:
    """Run compute provisioning shutdown steps in order, fail-fast by default."""

    for step in steps:
        try:
            await maybe_await(step.action())
        except Exception as exc:
            if logger is not None and step.error_message:
                logger.error(step.error_message, exc)
            if not step.continue_on_error:
                raise


async def stop_compute_provisioning_runtime(
    runtime: ComputeProvisioningRuntime,
    *,
    shutdown_steps: Sequence[ComputeProvisioningShutdownStep] = (),
    logger: LoggerLike | None = None,
) -> None:
    """Cancel background tasks and run shutdown steps."""

    await cancel_background_tasks(*runtime.background_tasks)
    await run_compute_provisioning_shutdown_steps(shutdown_steps, logger=logger)
