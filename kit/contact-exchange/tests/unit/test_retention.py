"""The retention window, its disclosure, and the one deletion operation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from market_contact_exchange import (
    ContactSettlementConfig,
    IntroductionRecord,
    IntroductionRetentionPolicy,
    IntroductionRetentionService,
    retention_disclosure,
    run_introduction_retention_sweep,
)

_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
_WINDOW = 3600


class Store:
    """In-memory persistence honouring the kit's selection and redaction contract."""

    def __init__(self, revealed: dict[str, datetime]) -> None:
        self.revealed = dict(revealed)
        self.deleted: dict[str, datetime] = {}
        self.delete_calls: list[str] = []
        self.fail_on: set[str] = set()

    async def select_expired(self, cutoff: datetime, limit: int) -> list[str]:
        eligible = sorted(
            (at, ref)
            for ref, at in self.revealed.items()
            if ref not in self.deleted and at <= cutoff
        )
        return [ref for _, ref in eligible[:limit]]

    async def delete_payloads(self, obligation_ref: str, deleted_at: datetime) -> bool:
        self.delete_calls.append(obligation_ref)
        if obligation_ref in self.fail_on:
            raise RuntimeError("database is locked")
        if obligation_ref not in self.revealed or obligation_ref in self.deleted:
            return False
        self.deleted[obligation_ref] = deleted_at
        return True

    async def load(self, obligation_ref: str) -> IntroductionRecord | None:
        if obligation_ref not in self.revealed:
            return None
        deleted_at = self.deleted.get(obligation_ref)
        return IntroductionRecord(
            obligation_ref=obligation_ref,
            agreement_ref="neg",
            buyer_contact={},
            seller_contact={},
            payloads_deleted_at=(
                deleted_at.strftime("%Y-%m-%dT%H:%M:%SZ") if deleted_at else None
            ),
        )


def _service(
    store: Store, *, window: int | None = _WINDOW, interval: int = 60
) -> IntroductionRetentionService:
    return IntroductionRetentionService(
        policy=IntroductionRetentionPolicy(
            window_seconds=window, sweep_interval_seconds=interval
        ),
        select_expired=store.select_expired,
        delete_payloads=store.delete_payloads,
        load=store.load,
        clock=lambda: _NOW,
    )


def test_the_policy_reads_the_configured_window() -> None:
    policy = IntroductionRetentionPolicy.from_config(
        ContactSettlementConfig(retention_seconds=90, retention_sweep_interval_seconds=7)
    )
    assert policy == IntroductionRetentionPolicy(
        window_seconds=90, sweep_interval_seconds=7
    )
    indefinite = IntroductionRetentionPolicy.from_config(
        ContactSettlementConfig(retention_seconds="indefinite")
    )
    assert indefinite.window_seconds is None
    assert indefinite.cutoff(_NOW) is None


def test_the_disclosure_states_current_policy_scoped_to_the_record() -> None:
    assert retention_disclosure(
        IntroductionRetentionPolicy(window_seconds=2592000, sweep_interval_seconds=60)
    ) == {
        "window_seconds": 2592000,
        "basis": "current_policy",
        "scope": "introduction_record",
    }
    assert retention_disclosure(
        IntroductionRetentionPolicy(window_seconds=None, sweep_interval_seconds=60)
    )["window_seconds"] is None


@pytest.mark.parametrize(
    "window, interval", [(0, 60), (-5, 60), (60, 0)]
)
def test_the_policy_refuses_non_positive_values(window: int, interval: int) -> None:
    with pytest.raises(ValueError):
        IntroductionRetentionPolicy(window_seconds=window, sweep_interval_seconds=interval)


async def test_eligibility_is_inclusive_at_the_window_boundary() -> None:
    boundary = _NOW - timedelta(seconds=_WINDOW)
    store = Store(
        {
            "at-boundary": boundary,
            "past": boundary - timedelta(seconds=1),
            "inside": boundary + timedelta(seconds=1),
        }
    )
    preview = await _service(store).preview()
    assert preview == {
        "loop": "introduction_retention",
        "dry_run": True,
        "eligible": ["past", "at-boundary"],
        "eligible_count": 2,
    }


async def test_the_preview_writes_nothing_and_the_step_deletes_exactly_it() -> None:
    store = Store({"old": _NOW - timedelta(days=1), "new": _NOW})
    service = _service(store)
    preview = await service.preview()
    assert store.delete_calls == []
    report = await service.sweep_once()
    assert report == {"loop": "introduction_retention", "deleted": 1}
    assert sorted(store.deleted) == preview["eligible"] == ["old"]


async def test_an_indefinite_window_deletes_nothing() -> None:
    store = Store({"ancient": _NOW - timedelta(days=3650)})
    service = _service(store, window=None)
    assert (await service.preview())["eligible"] == []
    assert await service.sweep_once() == {"loop": "introduction_retention", "deleted": 0}
    assert store.delete_calls == []


async def test_a_partially_failed_sweep_converges_on_the_next_cycle() -> None:
    store = Store(
        {
            "a": _NOW - timedelta(days=3),
            "b": _NOW - timedelta(days=2),
            "c": _NOW - timedelta(days=1),
        }
    )
    store.fail_on = {"b"}
    service = _service(store)
    with pytest.raises(RuntimeError):
        await service.sweep_once()
    assert sorted(store.deleted) == ["a"]
    store.fail_on = set()
    assert await service.sweep_once() == {"loop": "introduction_retention", "deleted": 2}
    assert sorted(store.deleted) == ["a", "b", "c"]


async def test_operator_deletion_ignores_the_window_and_converges() -> None:
    store = Store({"fresh": _NOW})
    service = _service(store)
    first = await service.delete_one("fresh")
    assert first == {
        "obligation_ref": "fresh",
        "redacted": True,
        "payloads_deleted_at": "2026-10-01T12:00:00Z",
    }
    again = await service.delete_one("fresh")
    assert again == {**first, "redacted": False}
    never = await service.delete_one("never-started")
    assert never == {
        "obligation_ref": "never-started",
        "redacted": False,
        "payloads_deleted_at": None,
    }


async def test_both_invocation_paths_use_the_one_deletion_operation() -> None:
    store = Store({"old": _NOW - timedelta(days=1), "asked": _NOW})
    service = _service(store)
    await service.delete_one("asked")
    await service.sweep_once()
    assert store.delete_calls == ["asked", "old"]


async def test_the_runner_gates_on_entry_and_before_each_sweep() -> None:
    store = Store({"old": _NOW - timedelta(days=1)})
    service = _service(store, interval=1)
    events: list[str] = []
    held = asyncio.Event()

    def paused() -> bool:
        events.append("gate")
        # Held from the second gate on, so the test observes the order of
        # gate, sweep, wait, gate.
        if events.count("gate") >= 2:
            held.set()
            return True
        return False

    async def wait(seconds: float) -> None:
        events.append("wait")

    original = service.sweep_once

    async def sweep_once():
        events.append("sweep")
        return await original()

    service.sweep_once = sweep_once  # type: ignore[method-assign]
    task = asyncio.create_task(
        run_introduction_retention_sweep(service, paused=paused, wait=wait)
    )
    await asyncio.wait_for(held.wait(), timeout=5)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    # The first gate is read on entry; the first sweep is not yet due, so the
    # runner waits, then reads the gate again before any work.
    assert events[:3] == ["gate", "wait", "gate"]
    assert "sweep" not in events


async def test_the_runner_sweeps_once_due_and_waits_between_cycles() -> None:
    store = Store({"old": _NOW - timedelta(days=1)})
    service = _service(store, interval=1)
    swept = asyncio.Event()
    waits: list[float] = []

    async def wait(seconds: float) -> None:
        waits.append(seconds)
        await asyncio.sleep(seconds)

    original = service.sweep_once

    async def sweep_once():
        report = await original()
        swept.set()
        return report

    service.sweep_once = sweep_once  # type: ignore[method-assign]
    task = asyncio.create_task(
        run_introduction_retention_sweep(service, paused=lambda: False, wait=wait)
    )
    await asyncio.wait_for(swept.wait(), timeout=5)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert sorted(store.deleted) == ["old"]
    assert waits and all(seconds == 1.0 for seconds in waits)


async def test_a_gated_runner_requires_an_interruptible_wait() -> None:
    with pytest.raises(TypeError, match="interruptible wait"):
        await run_introduction_retention_sweep(
            _service(Store({})), paused=lambda: False
        )
