"""Seller-side reconciliation runs each deal's settle and keeps going."""

from __future__ import annotations

import asyncio
import logging

import pytest

from market_arkhai_payments import reconcile_accepted_payments, run_payment_reconciliation

_LOGGER = logging.getLogger("test")


def test_one_failing_deal_does_not_stop_the_pass():
    settled: list[str] = []

    async def settle(negotiation_id: str) -> None:
        if negotiation_id == "bad":
            raise RuntimeError("payments service is unavailable")
        settled.append(negotiation_id)

    done = asyncio.run(reconcile_accepted_payments(["a", "bad", "b"], settle, logger=_LOGGER))

    assert (done.attempted, done.failed) == (3, 1)
    assert settled == ["a", "b"]


def test_the_loop_waits_skips_held_passes_and_survives_a_failure():
    passes: list[int] = []
    held = iter([False, True, False])

    async def reconcile_once() -> None:
        passes.append(len(passes))
        if len(passes) == 1:
            raise RuntimeError("transient")

    async def run() -> None:
        waits = 0

        async def wait(_seconds: float) -> None:
            nonlocal waits
            waits += 1
            if waits > 3:
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await run_payment_reconciliation(
                reconcile_once,
                interval_seconds=30,
                logger=_LOGGER,
                paused=lambda: next(held),
                wait=wait,
            )

    asyncio.run(run())

    # Three intervals: the first pass fails, the second is held, the third runs.
    assert passes == [0, 1]


def test_a_gate_requires_an_interruptible_wait():
    async def reconcile_once() -> None:
        return None

    with pytest.raises(TypeError):
        asyncio.run(
            run_payment_reconciliation(
                reconcile_once, interval_seconds=1, logger=_LOGGER, paused=lambda: False
            )
        )
