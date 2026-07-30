"""Background-only compute provisioning worker command."""

from __future__ import annotations

import asyncio
import logging
import signal

from compute_provisioning import (
    start_compute_provisioning_runtime,
    stop_compute_provisioning_runtime,
)

from compute_provisioning_service import app_runtime

logger = logging.getLogger(__name__)


async def run_worker(stop_event: asyncio.Event | None = None) -> None:
    """Run startup hooks and background loops until shutdown is requested."""

    requested_stop = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    if stop_event is None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, requested_stop.set)
                installed_signals.append(sig)
            except NotImplementedError:  # pragma: no cover - Windows event loop
                pass

    runtime = await start_compute_provisioning_runtime(
        startup_steps=app_runtime.startup_steps(),
        background_tasks=app_runtime.background_tasks,
        logger=logger,
    )
    try:
        await requested_stop.wait()
    finally:
        await stop_compute_provisioning_runtime(
            runtime,
            shutdown_steps=app_runtime.shutdown_steps(),
            logger=logger,
        )
        for sig in installed_signals:
            loop.remove_signal_handler(sig)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
