"""ClaimsEngine mechanics: state machine, retry/backoff, expiration."""

from __future__ import annotations

from typing import Any

import pytest

from core_storefront.settlement_lifecycle import ClaimRecord, ClaimsEngine


class FakeStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def due_claims(self, now_unix: float, limit: int = 50) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.rows.values()
            if r["state"] not in ("collected", "abandoned")
            and (r.get("next_attempt_unix") is None or r["next_attempt_unix"] <= now_unix)
        ][:limit]

    async def upsert_claim(self, claim: dict[str, Any]) -> None:
        self.rows.setdefault(claim["claim_ref"], dict(claim))

    async def save_claim(self, claim: dict[str, Any]) -> None:
        self.rows[claim["claim_ref"]] = dict(claim)


class ScriptedHooks:
    """check_conditions pops statuses from a script; collect pops outcomes."""

    def __init__(self, conditions: list[str], collects: list[Any]) -> None:
        self.conditions = list(conditions)
        self.collects = list(collects)
        self.condition_calls = 0
        self.collect_calls = 0

    async def check_conditions(self, claim: ClaimRecord) -> str:
        self.condition_calls += 1
        claim.mechanism_state["touched"] = self.condition_calls
        return self.conditions.pop(0)

    async def collect(self, claim: ClaimRecord) -> dict[str, Any] | None:
        self.collect_calls += 1
        outcome = self.collects.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _claim(ref: str = "esc-1", expiration: int = 4_102_444_800) -> ClaimRecord:
    return ClaimRecord(
        claim_ref=ref,
        deal_ref={"negotiation_id": "neg-1"},
        obligation={"mechanism": "alkahest.v1", "expiration_unix": expiration},
        fulfillment_ref="ful-1",
    )


def _engine(store, hooks, *, now=1_000.0, events=None):
    clock = lambda: now  # noqa: E731
    return ClaimsEngine(
        store,
        {"alkahest.v1": hooks},
        on_event=(lambda ev, **f: events.append((ev, f))) if events is not None else None,
        base_backoff_seconds=10,
        clock=clock,
    )


@pytest.mark.asyncio
async def test_ready_conditions_collect_in_one_sweep():
    store, events = FakeStore(), []
    hooks = ScriptedHooks(["ready"], [{"tx": "0xabc"}])
    engine = _engine(store, hooks, events=events)
    await engine.submit(_claim())

    assert await engine.tick() == 1
    row = store.rows["esc-1"]
    assert row["state"] == "collected"
    assert row["result"] == {"tx": "0xabc"}
    assert [e for e, _ in events] == [
        "claim_submitted", "claim_collectable", "claim_collected",
    ]


@pytest.mark.asyncio
async def test_pending_conditions_back_off_with_persistence():
    store = FakeStore()
    hooks = ScriptedHooks(["pending", "ready"], [{"tx": "0x1"}])
    engine = _engine(store, hooks)
    await engine.submit(_claim())

    await engine.tick()
    row = store.rows["esc-1"]
    assert row["state"] == "awaiting_conditions"
    assert row["attempts"] == 1
    assert row["next_attempt_unix"] == 1_000.0 + 10
    assert row["mechanism_state"]["touched"] == 1  # hook scratch persisted

    # Not due yet → untouched.
    assert await engine.tick() == 0

    # Re-run with a later clock: conditions ready → collected.
    later = ClaimsEngine(
        store, {"alkahest.v1": hooks}, base_backoff_seconds=10, clock=lambda: 1_011.0
    )
    await later.tick()
    assert store.rows["esc-1"]["state"] == "collected"


@pytest.mark.asyncio
async def test_collect_failure_retries_then_succeeds():
    store, events = FakeStore(), []
    hooks = ScriptedHooks(["ready"], [RuntimeError("revert: not yet"), {"tx": "0x2"}])
    engine = _engine(store, hooks, events=events)
    await engine.submit(_claim())

    await engine.tick()
    row = store.rows["esc-1"]
    assert row["state"] == "collectable"
    assert "not yet" in row["last_error"]
    assert row["attempts"] == 1

    later = ClaimsEngine(
        store, {"alkahest.v1": hooks}, base_backoff_seconds=10, clock=lambda: 2_000.0
    )
    await later.tick()
    assert store.rows["esc-1"]["state"] == "collected"
    assert hooks.condition_calls == 1  # collectable state skips re-checking


@pytest.mark.asyncio
async def test_failed_conditions_abandon():
    store, events = FakeStore(), []
    hooks = ScriptedHooks(["failed"], [])
    engine = _engine(store, hooks, events=events)
    await engine.submit(_claim())

    await engine.tick()
    assert store.rows["esc-1"]["state"] == "abandoned"
    assert ("claim_abandoned", ) [0] in [e for e, _ in events]
    assert hooks.collect_calls == 0


@pytest.mark.asyncio
async def test_expiration_grace_abandons_uncollected():
    store = FakeStore()
    hooks = ScriptedHooks(["pending"] * 10, [])
    engine = ClaimsEngine(
        store, {"alkahest.v1": hooks},
        expiration_grace_seconds=100, clock=lambda: 5_000.0,
    )
    await engine.submit(_claim(expiration=4_000))  # 5000 > 4000 + 100

    await engine.tick()
    assert store.rows["esc-1"]["state"] == "abandoned"
    assert "expiration" in store.rows["esc-1"]["last_error"]


@pytest.mark.asyncio
async def test_unknown_mechanism_backs_off_not_abandons():
    store = FakeStore()
    engine = ClaimsEngine(store, {}, base_backoff_seconds=10, clock=lambda: 1_000.0)
    await engine.submit(_claim())

    await engine.tick()
    row = store.rows["esc-1"]
    assert row["state"] == "awaiting_conditions"
    assert "no hooks" in row["last_error"]
    assert row["next_attempt_unix"] == 1_010.0


@pytest.mark.asyncio
async def test_hook_exception_in_conditions_backs_off():
    store = FakeStore()

    class Boom:
        async def check_conditions(self, claim):
            raise ValueError("classifier exploded")

        async def collect(self, claim):
            return None

    engine = ClaimsEngine(
        store, {"alkahest.v1": Boom()}, base_backoff_seconds=10, clock=lambda: 1_000.0
    )
    await engine.submit(_claim())
    await engine.tick()
    row = store.rows["esc-1"]
    assert row["state"] == "awaiting_conditions"
    assert "classifier exploded" in row["last_error"]


@pytest.mark.asyncio
async def test_submit_is_idempotent():
    store = FakeStore()
    hooks = ScriptedHooks(["ready"], [{"tx": "0x3"}])
    engine = _engine(store, hooks)
    claim = _claim()
    await engine.submit(claim)
    await engine.tick()
    await engine.submit(claim)  # re-submit after collection
    assert store.rows["esc-1"]["state"] == "collected"
