"""The system routes the app mounts reach the workers the container composes.

Each side can be correct on its own while the wiring between them is missing,
so a control would answer that its worker is not initialised to every caller.
The routes resolve the workers through accessors; this binds those accessors,
on the routers ``main.py`` actually mounts, to the container's resolved workers.
"""

from __future__ import annotations

import pytest

from compute_provisioning_service import container as container_module
from compute_provisioning_service import main


class _Watchdog:
    is_paused = True

    def __init__(self) -> None:
        self.cycles = 0
        self.advances = 0

    async def run_cycle(self) -> dict[str, object]:
        self.cycles += 1
        return {"converged": 1}

    async def advance_cycle(self) -> dict[str, object]:
        self.advances += 1
        return {"converged": 1}


class _LeaseLifecycle:
    def __init__(self) -> None:
        self.cycles = 0

    async def force_check_leases(self) -> dict[str, int]:
        self.cycles += 1
        return {"checked": 0}


def _endpoint(path: str):
    for route in main._system_router.routes:
        if route.path == path:
            return route.endpoint
    raise AssertionError(f"the mounted system router has no {path}")


@pytest.fixture
def composed(monkeypatch):
    watchdog, lifecycle = _Watchdog(), _LeaseLifecycle()
    monkeypatch.setattr(
        container_module, "resolved_fulfillment_convergence_watchdog", watchdog
    )
    monkeypatch.setattr(container_module, "resolved_lease_lifecycle_service", lifecycle)
    return watchdog, lifecycle


async def test_the_convergence_controls_reach_the_composed_watchdog(composed):
    watchdog, _ = composed

    await _endpoint("/system/fulfillment-convergence/run-cycle")()
    await _endpoint("/system/fulfillment-convergence/advance-cycle")()

    assert (watchdog.cycles, watchdog.advances) == (1, 1)


async def test_check_leases_reaches_the_composed_lease_lifecycle(composed):
    _, lifecycle = composed

    await _endpoint("/system/check-leases")()

    assert lifecycle.cycles == 1
