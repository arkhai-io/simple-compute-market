"""The container hands each service the collaborators it needs.

`_system_service` is the seam between the container's providers and the VM
runtime's factory. It silently dropped the fulfillment convergence watchdog: the
endpoint, the service method, and the watchdog all existed and were never
connected, so the operator one-cycle control answered "not initialised" in every
deployment. A provider that forgets an argument fails nowhere at import time — it
fails at the one call site that needs it, which here was reachable only from an
end-to-end stage.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from compute_provisioning_service.container import _system_service


class TestSystemServiceWiring:
    def test_the_convergence_watchdog_reaches_the_runtime_factory(self) -> None:
        runtime = MagicMock()
        watchdog = object()
        lease_lifecycle = object()

        _system_service(
            runtime=runtime,
            lease_lifecycle_service=lease_lifecycle,
            fulfillment_convergence_watchdog=watchdog,
        )

        kwargs = runtime.system_service.call_args.kwargs
        assert kwargs["fulfillment_convergence_watchdog"] is watchdog, (
            "the watchdog must be the same instance the timer drives — a manual "
            "cycle that ran a different one would not exercise production behaviour"
        )
        assert kwargs["lease_lifecycle_service"] is lease_lifecycle
