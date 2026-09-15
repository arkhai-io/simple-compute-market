"""The admin convergence route reaches the watchdog it exists to advance.

`SystemService` has accepted a `fulfillment_convergence_watchdog` since the
route was added and nothing ever passed one, so
`POST /api/v1/system/fulfillment-convergence/run-cycle` answered
`503 fulfillment_convergence_watchdog not initialised` for every caller. A
parameter with a `None` default and no supplier is invisible to every test
that exercises either side on its own, which is why this binds the wiring
rather than the service.
"""

from __future__ import annotations

import pytest
from vm_provisioning_adapter.services.system_service import SystemService


class _Watchdog:
    def __init__(self) -> None:
        self.cycles = 0

    async def run_cycle(self) -> dict[str, object]:
        self.cycles += 1
        return {"converged": 1, "skipped": 0}


class _Runtime:
    """The adapter runtime's construction seam, with nothing else attached."""

    ansible_service = object()
    config = object()
    host_service = None
    session_factory = None
    job_queue_provider = None

    def system_service(
        self,
        *,
        lease_lifecycle_service,
        fulfillment_convergence_watchdog=None,
    ):
        return SystemService(
            ansible_service=self.ansible_service,
            settings=self.config,
            host_service=self.host_service,
            session_factory=self.session_factory,
            job_queue_provider=self.job_queue_provider,
            lease_lifecycle_service=lease_lifecycle_service,
            fulfillment_convergence_watchdog=fulfillment_convergence_watchdog,
        )


async def test_the_container_seam_forwards_the_watchdog():
    """`_system_service` is the only place these two singletons meet."""
    from compute_provisioning_service.container import _system_service

    watchdog = _Watchdog()
    service = _system_service(
        _Runtime(),
        lease_lifecycle_service=None,
        fulfillment_convergence_watchdog=watchdog,
    )

    result = await service.force_fulfillment_convergence()

    assert "error" not in result, (
        "the composed system service could not reach its watchdog, so the "
        "admin convergence route has nothing to advance"
    )
    assert watchdog.cycles == 1, "exactly one cycle per call"


async def test_an_absent_watchdog_still_refuses_by_name():
    """The refusal stays: a service composed without one says which one."""
    service = _Runtime().system_service(lease_lifecycle_service=None)

    result = await service.force_fulfillment_convergence()

    assert result.get("error") == "fulfillment_convergence_watchdog not initialised"


def test_the_container_declares_the_dependency():
    """Reading the provider's own arguments, not the service it built.

    The forwarding test above passes a watchdog in by hand, so it would also
    pass while the container still omitted it -- which is exactly the state
    that shipped.
    """
    from compute_provisioning_service import container as container_module

    provider = container_module.Container.system_service
    assert "fulfillment_convergence_watchdog" in provider.kwargs, (
        "the container's system_service provider does not pass the "
        f"convergence watchdog; it passes {sorted(provider.kwargs)}"
    )


if __name__ == "__main__":  # pragma: no cover - convenience
    raise SystemExit(pytest.main([__file__]))
