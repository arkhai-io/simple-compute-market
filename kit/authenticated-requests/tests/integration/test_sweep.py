"""The sweep the core runs from an authority's lifespan."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from market_identity import Signer

from market_authenticated_requests import REPLAY_TABLE
from tests.integration.support import SKEW, Caller, advance, make_world
from tests.integration.stepping import SteppedSleep


def rows(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {REPLAY_TABLE}").fetchone()[0])


def test_the_lifespan_sweeps_at_startup_then_every_interval(tmp_path: Path, caller_signer: Signer) -> None:
    sleep = SteppedSleep()
    world = make_world(tmp_path, "dependency", caller_signer, sleep=sleep)

    async def scenario(caller: Caller) -> None:
        for index in range(3):
            response = await caller.send(
                "GET", "/items/a", operation="item_read", resource="a", request_id=f"read-{index}"
            )
            assert response.status_code == 200
        assert rows(world.toy.database) == 3
        advance(2 * SKEW)

        async with world.core.sweeping():
            await sleep.waiting()
            assert rows(world.toy.database) == 0

            await caller.send("GET", "/items/a", operation="item_read", resource="a", request_id="read-late")
            assert rows(world.toy.database) == 1
            advance(2 * SKEW)
            await sleep.step()
            assert rows(world.toy.database) == 0
            assert sleep.asked == [world.core.settings.replay_prune_interval_seconds] * 2

    world.run(scenario)


class FailsOnce:
    """A replay store whose first sweep fails, as under a lock held too long."""

    def __init__(self, store: object) -> None:
        self._store = store
        self.failed = False

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def sweep_batch(self, *, now: int, limit: int) -> int:
        if not self.failed:
            self.failed = True
            raise sqlite3.OperationalError("database is locked")
        return int(self._store.sweep_batch(now=now, limit=limit))  # type: ignore[attr-defined]


def test_a_sweep_that_fails_is_logged_and_the_next_interval_sweeps(tmp_path: Path, caller_signer: Signer) -> None:
    sleep = SteppedSleep()
    failing: list[FailsOnce] = []

    def wrap(store: object) -> FailsOnce:
        failing.append(FailsOnce(store))
        return failing[0]

    world = make_world(tmp_path, "dependency", caller_signer, sleep=sleep, wrap_store=wrap)

    async def scenario(caller: Caller) -> None:
        await caller.send("GET", "/items/a", operation="item_read", resource="a", request_id="read-1")
        advance(2 * SKEW)

        async with world.core.sweeping():
            await sleep.waiting()
            assert failing[0].failed and rows(world.toy.database) == 1
            await sleep.step()
            assert rows(world.toy.database) == 0

    world.run(scenario)
