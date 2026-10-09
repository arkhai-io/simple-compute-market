"""The framework-free lifecycle routes answer one shape for every storefront."""

from __future__ import annotations

import asyncio

import pytest

from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront_kit import (
    LifecycleRouteError,
    StorefrontLifecycleRouteService,
    StorefrontLoopController,
)


@pytest.fixture
async def controller():
    loops = StorefrontLoopController()
    yield loops
    handles = list(loops._handles.values())
    loops.clear_loops()
    await asyncio.gather(*handles, return_exceptions=True)


async def test_pause_and_resume_report_every_loop(controller):
    gated = asyncio.Event()

    async def _loop() -> None:
        while True:
            if controller.gate("alpha"):
                await asyncio.Event().wait()
            gated.set()
            await controller.idle(3600)

    controller.start_loop(StorefrontBackgroundTask(name="alpha", task_factory=_loop))
    service = StorefrontLifecycleRouteService(controller)
    await asyncio.wait_for(gated.wait(), timeout=1)

    assert await service.pause() == {"paused": True, "loops": {"alpha": "paused"}}
    assert await service.resume() == {"paused": False, "loops": {"alpha": "running"}}


async def test_a_step_result_is_returned_unchanged(controller):
    async def _step():
        return {"loop": "publication", "counts": {"published": 2}}

    controller.register_step("publication", route="publication", step=_step)
    service = StorefrontLifecycleRouteService(controller)

    assert await service.run_cycle("publication") == {
        "loop": "publication",
        "counts": {"published": 2},
    }


@pytest.mark.parametrize("call", ["run_cycle", "dry_run"])
async def test_an_unknown_loop_is_not_found(controller, call):
    service = StorefrontLifecycleRouteService(controller)
    with pytest.raises(LifecycleRouteError) as raised:
        await getattr(service, call)("capacity-events")
    assert raised.value.status_code == 404


async def test_a_loop_without_a_preview_is_not_found_for_a_dry_run(controller):
    async def _step():
        return {}

    controller.register_step("publication", route="publication", step=_step)
    service = StorefrontLifecycleRouteService(controller)
    with pytest.raises(LifecycleRouteError) as raised:
        await service.dry_run("publication")
    assert raised.value.status_code == 404
