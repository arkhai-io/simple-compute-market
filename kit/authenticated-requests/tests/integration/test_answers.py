"""The core's answers after admission, and its renewal around a recorded handler.

Library integration in each form, as the admission tests are. A handler's lease
renewal is stepped by the test through the core's injected ``sleep``, never slept.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx
import injected_time
import pytest
from market_identity import Signer

from market_authenticated_requests import ROUTE_FAILURE_DETAIL
from tests.integration.stepping import STEP_BOUND, SteppedSleep
from tests.integration.support import LEASE, RETENTION, START, Caller, World, advance, make_world


def test_a_recorded_route_answers_its_exact_retry_with_the_recorded_outcome(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        first = await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5})
        later = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 9}, request_id="request-2"
        )
        advance(600)
        retry = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5}, origin=START
        )

        assert later.status_code == 200
        assert (retry.status_code, retry.content) == (first.status_code, first.content)
        assert caller.verified(retry, method="POST", operation="item_set", resource="a")
        assert retry.headers["signature"] != first.headers["signature"]

    world.run(scenario)
    assert world.toy.dispatches == {"item_set": 2}
    assert world.toy.items() == {"a": 9}


def test_a_rerun_route_runs_its_exact_retry_again_told_it_is_a_retry(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        await caller.send("POST", "/items/a/raise", operation="item_raise", resource="a", body={"value": 5})
        await caller.send(
            "POST", "/items/a/raise", operation="item_raise", resource="a", body={"value": 9}, request_id="request-2"
        )
        retry = await caller.send(
            "POST", "/items/a/raise", operation="item_raise", resource="a", body={"value": 5}, origin=START
        )

        assert retry.status_code == 200 and retry.json() == {"item": "a", "value": 9}
        assert caller.verified(retry, method="POST", operation="item_raise", resource="a")

    world.run(scenario)
    assert world.toy.retries == [False, False, True]
    assert world.toy.items() == {"a": 9}


def test_a_recorded_route_that_raises_after_writing_is_a_recorded_signed_500(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario(caller: Caller) -> None:
        with caplog.at_level(logging.ERROR, logger="market_authenticated_requests"):
            failed = await caller.send("POST", "/fail", operation="fail_recorded")
        retry = await caller.send("POST", "/fail", operation="fail_recorded")

        assert failed.status_code == 500 and failed.json() == {"detail": ROUTE_FAILURE_DETAIL}
        assert caller.verified(failed, method="POST", operation="fail_recorded")
        assert (retry.status_code, retry.content) == (500, failed.content)
        assert caller.verified(retry, method="POST", operation="fail_recorded")

    world.run(scenario)
    assert world.toy.dispatches == {"fail_recorded": 1}
    assert world.toy.items() == {"failed": 1}
    assert "a secret detail of the failure" in caplog.text
    assert "secret" not in ROUTE_FAILURE_DETAIL


def test_a_rerun_route_that_raises_is_a_signed_500_and_its_retry_runs_again(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        failed = await caller.send("POST", "/fail-again", operation="fail_rerun")
        retry = await caller.send("POST", "/fail-again", operation="fail_rerun")

        assert failed.status_code == 500 and failed.json() == {"detail": ROUTE_FAILURE_DETAIL}
        assert caller.verified(failed, method="POST", operation="fail_rerun")
        assert retry.status_code == 500

    world.run(scenario)
    assert world.toy.dispatches == {"fail_rerun": 2}


def test_a_recorded_retry_older_than_the_retention_is_a_signed_410(world: World) -> None:
    async def scenario(caller: Caller) -> None:
        await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5})
        advance(RETENTION + 1)
        retry = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5}, origin=START
        )

        assert retry.status_code == 410 and retry.json()["code"] == "exact_retry_expired"
        assert caller.verified(retry, method="POST", operation="item_set", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {"item_set": 1}


def test_the_signed_outcome_hook_receives_the_exact_bytes_and_headers_sent(world: World) -> None:
    sent: list[httpx.Response] = []

    async def scenario(caller: Caller) -> None:
        sent.append(await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5}))
        sent.append(await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 6}))

    world.run(scenario)

    assert len(world.outcomes) == 2
    for outcome, response in zip(world.outcomes, sent):
        assert (outcome.status, outcome.body) == (response.status_code, response.content)
        assert list(outcome.headers) == [(name.decode(), value.decode()) for name, value in response.headers.raw]
        assert outcome.request.operation == "item_set"


class LosesItsRecord:
    """A replay store whose record never lands after the handler's commit, as when
    its database refuses the write."""

    def __init__(self, store: object) -> None:
        self._store = store

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def record(self, *args: object, **kwargs: object) -> bool:
        raise ConnectionError("the authority stopped before recording the outcome")


def test_an_outcome_never_recorded_is_outcome_unknown_and_never_dispatched_again(
    tmp_path: Path, form: str, caller_signer: Signer
) -> None:
    world = make_world(tmp_path, form, caller_signer, wrap_store=LosesItsRecord)

    async def scenario(caller: Caller) -> None:
        answered = await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5})
        assert answered.status_code == 200
        assert caller.verified(answered, method="POST", operation="item_set", resource="a")
        advance(LEASE)
        retry = await caller.send(
            "POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5}, origin=START
        )

        assert retry.status_code == 409 and retry.json()["code"] == "exact_retry_outcome_unknown"
        assert caller.verified(retry, method="POST", operation="item_set", resource="a")
        read = await caller.send("GET", "/items/a", operation="item_read", resource="a", request_id="read-1")
        assert read.json() == {"item": "a", "value": 5}

    world.run(scenario)
    assert world.toy.dispatches == {"item_set": 1}


def test_a_recorded_handler_running_past_its_lease_is_renewed_then_answers(
    tmp_path: Path, form: str, caller_signer: Signer
) -> None:
    sleep = SteppedSleep()
    world = make_world(tmp_path, form, caller_signer, sleep=sleep)

    async def scenario(caller: Caller) -> None:
        first = asyncio.create_task(caller.send("POST", "/slow", operation="slow_recorded"))
        await asyncio.wait_for(world.toy.slow_started.wait(), STEP_BOUND)
        advance(LEASE // 3)
        await sleep.step()
        advance(LEASE - 5)
        assert injected_time.now() > START + LEASE
        in_progress = await caller.send("POST", "/slow", operation="slow_recorded", origin=START)
        assert in_progress.status_code == 409
        assert in_progress.json() == {"detail": "The authenticated request is still in progress"}

        assert sleep.asked == [LEASE / 3, LEASE / 3]
        world.toy.slow_finish.set()
        answered = await asyncio.wait_for(first, STEP_BOUND)
        retry = await caller.send("POST", "/slow", operation="slow_recorded", origin=START)

        assert answered.status_code == 200
        assert (retry.status_code, retry.content) == (200, answered.content)
        assert caller.verified(retry, method="POST", operation="slow_recorded")

    world.run(scenario)
    assert world.toy.dispatches == {"slow_recorded": 1}


class RefusesToReserve:
    """A replay store whose every reservation fails, as under a lock held too long."""

    def __init__(self, store: object) -> None:
        self._store = store

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def claim(self, *args: object, **kwargs: object) -> object:
        raise ConnectionError("database is locked")


def test_a_reservation_that_fails_is_a_signed_500_and_nothing_is_dispatched(
    tmp_path: Path, form: str, caller_signer: Signer
) -> None:
    world = make_world(tmp_path, form, caller_signer, wrap_store=RefusesToReserve)

    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5})

        assert response.status_code == 500 and response.json() == {"detail": ROUTE_FAILURE_DETAIL}
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {}


def test_a_cancelled_recorded_handler_stops_renewing_its_lease(
    tmp_path: Path, form: str, caller_signer: Signer
) -> None:
    sleep = SteppedSleep()
    world = make_world(tmp_path, form, caller_signer, sleep=sleep)

    async def scenario(caller: Caller) -> None:
        first = asyncio.create_task(caller.send("POST", "/slow", operation="slow_recorded"))
        await asyncio.wait_for(world.toy.slow_started.wait(), STEP_BOUND)
        await sleep.waiting()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await asyncio.sleep(0)
        # Only this task is left: the cancelled attempt's renewal stopped with it.
        assert all(task is asyncio.current_task() for task in asyncio.all_tasks())

    world.run(scenario)
