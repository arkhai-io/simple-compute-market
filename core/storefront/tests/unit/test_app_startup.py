import pytest

from core_storefront.app_startup import (
    StorefrontBackgroundTask,
    StorefrontStartupStep,
    run_storefront_startup_steps,
    start_storefront_background_task,
)


class CapturingLogger:
    def __init__(self):
        self.infos: list[tuple[str, tuple]] = []
        self.errors: list[tuple[str, tuple]] = []

    def info(self, msg: str, *args, **kwargs) -> None:
        self.infos.append((msg, args))

    def error(self, msg: str, *args, **kwargs) -> None:
        self.errors.append((msg, args))


@pytest.mark.asyncio
async def test_run_storefront_startup_steps_runs_sync_and_async_steps_in_order():
    events: list[str] = []

    async def async_step() -> None:
        events.append("async")

    await run_storefront_startup_steps(
        (
            StorefrontStartupStep("sync", lambda: events.append("sync")),
            StorefrontStartupStep("async", async_step),
        )
    )

    assert events == ["sync", "async"]


@pytest.mark.asyncio
async def test_run_storefront_startup_steps_can_continue_after_noncritical_error():
    logger = CapturingLogger()
    events: list[str] = []

    def boom() -> None:
        events.append("boom")
        raise RuntimeError("nope")

    await run_storefront_startup_steps(
        (
            StorefrontStartupStep(
                "best_effort",
                boom,
                continue_on_error=True,
                error_message="failed: %s",
            ),
            StorefrontStartupStep("next", lambda: events.append("next")),
        ),
        logger=logger,
    )

    assert events == ["boom", "next"]
    assert logger.errors[0][0] == "failed: %s"
    assert isinstance(logger.errors[0][1][0], RuntimeError)


@pytest.mark.asyncio
async def test_run_storefront_startup_steps_raises_after_critical_error():
    logger = CapturingLogger()
    events: list[str] = []

    def boom() -> None:
        events.append("boom")
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        await run_storefront_startup_steps(
            (
                StorefrontStartupStep("critical", boom, error_message="failed: %s"),
                StorefrontStartupStep("next", lambda: events.append("next")),
            ),
            logger=logger,
        )

    assert events == ["boom"]
    assert logger.errors[0][0] == "failed: %s"


def test_start_storefront_background_task_schedules_and_logs():
    logger = CapturingLogger()
    scheduled = []

    async def worker() -> None:
        return None

    def create_task(coro):
        scheduled.append(coro)
        return "handle"

    handle = start_storefront_background_task(
        StorefrontBackgroundTask(
            name="worker",
            task_factory=worker,
            log_message="started %s",
            log_args=("worker",),
        ),
        logger=logger,
        create_task=create_task,
    )

    assert handle == "handle"
    assert len(scheduled) == 1
    assert logger.infos == [("started %s", ("worker",))]

    scheduled[0].close()
