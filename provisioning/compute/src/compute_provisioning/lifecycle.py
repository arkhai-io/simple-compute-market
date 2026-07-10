"""Reusable lifecycle helpers for provisioning executables."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable


async def cancel_background_tasks(*tasks: asyncio.Task | None) -> None:
    """Cancel background tasks and wait for cancellation to settle.

    Provisioning services commonly start a small set of long-running asyncio
    loops during FastAPI lifespan startup. This helper centralizes the shutdown
    pattern while preserving each executable's ownership of what tasks to start.
    """

    for task in tasks:
        if task is not None:
            task.cancel()

    for task in tasks:
        if task is None:
            continue
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_background_task(coro: Awaitable, *, name: str) -> asyncio.Task:
    """Create a named asyncio background task."""

    return asyncio.create_task(coro, name=name)
