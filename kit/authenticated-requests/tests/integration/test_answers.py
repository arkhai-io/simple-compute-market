"""The core's answers after admission, and its renewal around a recorded handler.

Library integration in each form, as the admission tests are. A handler's lease
renewal is stepped by the test through the core's injected ``sleep``, never slept.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import injected_time
import pytest
from market_identity import Signer, TrustedIdentitySet, verify_request_evidence, verify_response_evidence

from market_authenticated_requests import ADMISSION_UNAVAILABLE_DETAIL, ROUTE_FAILURE_DETAIL
from tests.integration.stepping import STEP_BOUND, SteppedSleep
from tests.integration.support import LEASE, RETENTION, SKEW, START, Caller, World, advance, make_world


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


def test_the_signed_outcome_hook_receives_both_records_and_both_bodies(world: World) -> None:
    sent: list[httpx.Response] = []

    async def scenario(caller: Caller) -> None:
        sent.append(await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5}))
        sent.append(await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 6}))

    world.run(scenario)

    caller = TrustedIdentitySet(identities=(world.caller_signer.identity,))
    authority = TrustedIdentitySet(identities=(world.authority.identity,))
    assert len(world.outcomes) == 2
    for outcome, response, value in zip(world.outcomes, sent, (5, 6)):
        assert outcome.request_body == json.dumps({"value": value}).encode()
        assert (outcome.response.status, outcome.response_body) == (response.status_code, response.content)
        request = verify_request_evidence(
            json.loads(outcome.request.model_dump_json()), body=outcome.request_body, trusted=caller,
            expected_role="seller", expected_operation="item_set", expected_resource="a",
        )
        answer = verify_response_evidence(
            json.loads(outcome.response.model_dump_json()), body=outcome.response_body, trusted=authority,
            expected_operation="item_set", expected_resource="a",
        )
        assert request.verified and answer.verified
        assert answer.evidence is not None and answer.evidence.request_id == outcome.request.request_id


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


class RefusesEveryRenewal:
    """A replay store that refuses every renewal, as under a write lock held past
    the lease."""

    def __init__(self, store: object) -> None:
        self._store = store

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def renew(self, *args: object, **kwargs: object) -> bool:
        raise ConnectionError("database is locked")


def test_a_recorded_handler_whose_renewals_all_fail_loses_its_lease_while_it_runs(
    tmp_path: Path, form: str, caller_signer: Signer, caplog: pytest.LogCaptureFixture
) -> None:
    # The residual case of a live attempt losing its lease: its retry is told the
    # outcome is unknown, the loss is logged as an error, and the attempt still
    # answers and records its outcome.
    sleep = SteppedSleep()
    world = make_world(tmp_path, form, caller_signer, sleep=sleep, wrap_store=RefusesEveryRenewal)
    lost = "lost its lease while its handler runs"

    async def scenario(caller: Caller) -> None:
        with caplog.at_level(logging.WARNING, logger="request_replay.renewal"):
            first = asyncio.create_task(caller.send("POST", "/slow", operation="slow_recorded"))
            await asyncio.wait_for(world.toy.slow_started.wait(), STEP_BOUND)
            advance(LEASE // 3)
            await sleep.step()
            advance(LEASE // 3)
            await sleep.step()
            assert not [record for record in caplog.records if lost in record.getMessage()]
            advance(LEASE - 2 * (LEASE // 3))
            await sleep.last_step()
            await asyncio.sleep(0)
            unknown = await caller.send("POST", "/slow", operation="slow_recorded", origin=START)

        assert unknown.status_code == 409 and unknown.json()["code"] == "exact_retry_outcome_unknown"
        assert caller.verified(unknown, method="POST", operation="slow_recorded")
        (loss,) = [record for record in caplog.records if lost in record.getMessage()]
        assert loss.levelno == logging.ERROR and "request-1" in loss.getMessage()
        assert not first.done()

        world.toy.slow_finish.set()
        answered = await asyncio.wait_for(first, STEP_BOUND)
        retry = await caller.send("POST", "/slow", operation="slow_recorded", origin=START)

        assert answered.status_code == 200
        assert (retry.status_code, retry.content) == (200, answered.content)

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


UNAVAILABLE = {"code": "admission_unavailable", "detail": ADMISSION_UNAVAILABLE_DETAIL}


@pytest.mark.parametrize(
    ("path", "operation", "resource"),
    [("/items/a/set", "item_set", "a"), ("/items/a/raise", "item_raise", "a")],
    ids=["recorded", "rerun"],
)
def test_a_reservation_the_store_refuses_is_a_signed_503_and_nothing_is_dispatched(
    tmp_path: Path, form: str, caller_signer: Signer, path: str, operation: str, resource: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make_world(tmp_path, form, caller_signer, wrap_store=RefusesToReserve)

    async def scenario(caller: Caller) -> None:
        with caplog.at_level(logging.ERROR, logger="market_authenticated_requests"):
            response = await caller.send("POST", path, operation=operation, resource=resource, body={"value": 5})

        assert response.status_code == 503 and response.json() == UNAVAILABLE
        assert caller.verified(response, method="POST", operation=operation, resource=resource)

    world.run(scenario)
    assert world.toy.dispatches == {}
    (logged,) = [record for record in caplog.records if "failed in the replay store" in record.getMessage()]
    assert logged.levelno == logging.ERROR and "request-1" in logged.getMessage()


class RefusesRenewalsThenWrites:
    """A replay store that refuses every renewal, and every write while the test
    holds it closed, as a database locked for longer than a lease."""

    WRITES = ("claim", "conclude", "record", "renew", "reclaim", "release")

    def __init__(self, store: object) -> None:
        self._store = store
        self.closed = False

    def __getattr__(self, name: str) -> object:
        target = getattr(self._store, name)
        if name == "renew" or (self.closed and name in self.WRITES):

            def refused(*args: object, **kwargs: object) -> object:
                raise ConnectionError("database is locked")

            return refused
        return target


# A retry within the skew meets the closed store at its claim; one older than the
# skew reads the row and meets it at the concluding write.
@pytest.mark.parametrize("later", [0, SKEW], ids=["within-the-skew", "older-than-the-skew"])
def test_a_store_refusing_renewals_then_writes_answers_the_retry_503_then_the_outcome(
    tmp_path: Path, form: str, caller_signer: Signer, caplog: pytest.LogCaptureFixture, later: int
) -> None:
    sleep = SteppedSleep()
    stores: list[RefusesRenewalsThenWrites] = []

    def wrap(store: object) -> RefusesRenewalsThenWrites:
        stores.append(RefusesRenewalsThenWrites(store))
        return stores[-1]

    world = make_world(tmp_path, form, caller_signer, sleep=sleep, wrap_store=wrap)
    lost = "lost its lease while its handler runs"

    async def scenario(caller: Caller) -> None:
        (store,) = stores
        with caplog.at_level(logging.WARNING, logger="request_replay.renewal"):
            first = asyncio.create_task(caller.send("POST", "/slow", operation="slow_recorded"))
            await asyncio.wait_for(world.toy.slow_started.wait(), STEP_BOUND)
            advance(LEASE // 3)
            await sleep.step()
            advance(LEASE // 3)
            await sleep.step()
            advance(LEASE - 2 * (LEASE // 3))
            await sleep.last_step()
            store.closed = True
            advance(later)
            unavailable = await caller.send("POST", "/slow", operation="slow_recorded", origin=START)

            assert unavailable.status_code == 503 and unavailable.json() == UNAVAILABLE
            assert caller.verified(unavailable, method="POST", operation="slow_recorded")
            store.closed = False
            world.toy.slow_finish.set()
            answered = await asyncio.wait_for(first, STEP_BOUND)

        (loss,) = [record for record in caplog.records if lost in record.getMessage()]
        assert loss.levelno == logging.ERROR and "request-1" in loss.getMessage()
        retry = await caller.send("POST", "/slow", operation="slow_recorded", origin=START)

        assert answered.status_code == 200
        assert (retry.status_code, retry.content) == (200, answered.content)
        assert caller.verified(retry, method="POST", operation="slow_recorded")

    world.run(scenario)
    assert world.toy.dispatches == {"slow_recorded": 1}


@pytest.mark.parametrize("store_kind", ["sqlite3", "sqlalchemy"])
@pytest.mark.parametrize("waited", [LEASE, SKEW + 1], ids=["within-the-skew", "older-than-the-skew"])
def test_a_retry_while_the_handler_holds_the_database_is_concluded_only_after_its_commit(
    tmp_path: Path, form: str, caller_signer: Signer, store_kind: str, waited: int
) -> None:
    # The replay store meets the handler's write lock with no busy timeout, so the
    # retry is answered at once rather than after a wait; and the lease is never
    # renewed, its renewal's waits never stepped. A retry within the skew meets the
    # lock at its claim; one older than the skew reads the row, which on the
    # SQLAlchemy store passes the lock, and meets it at the concluding write.
    world = make_world(
        tmp_path, form, caller_signer, store_kind=store_kind, busy_timeout=0, sleep=SteppedSleep()
    )

    async def scenario(caller: Caller) -> None:
        first = asyncio.create_task(caller.send("POST", "/hold", operation="hold_recorded"))
        await asyncio.wait_for(world.toy.hold_started.wait(), STEP_BOUND)
        advance(waited)

        held = await caller.send("POST", "/hold", operation="hold_recorded", origin=START)
        assert held.status_code == 503 and held.json() == UNAVAILABLE
        assert caller.verified(held, method="POST", operation="hold_recorded")

        world.toy.hold_commit.set()
        await asyncio.wait_for(world.toy.hold_committed.wait(), STEP_BOUND)
        unknown = await caller.send("POST", "/hold", operation="hold_recorded", origin=START)
        assert unknown.status_code == 409 and unknown.json()["code"] == "exact_retry_outcome_unknown"
        assert caller.verified(unknown, method="POST", operation="hold_recorded")

        read = await caller.send("GET", "/items/held", operation="item_read", resource="held", request_id="read-1")
        assert read.json() == {"item": "held", "value": 1}
        replaced = await caller.send(
            "POST", "/items/held/set", operation="item_set", resource="held", body={"value": 2}, request_id="set-1"
        )
        assert replaced.status_code == 200

        world.toy.hold_finish.set()
        answered = await asyncio.wait_for(first, STEP_BOUND)
        assert answered.status_code == 200
        retry = await caller.send("POST", "/hold", operation="hold_recorded", origin=START)
        assert (retry.status_code, retry.content) == (200, answered.content)

    world.run(scenario)
    assert world.toy.read("held") == 2
    assert world.toy.dispatches == {"hold_recorded": 1, "item_set": 1}


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


def test_a_trust_that_fails_while_admitting_is_a_signed_500_and_nothing_is_dispatched(
    tmp_path: Path, form: str, caller_signer: Signer
) -> None:
    def failing_trust(role: str) -> TrustedIdentitySet:
        raise LookupError("the trust store is unreachable")

    world = make_world(tmp_path, form, caller_signer, trust=failing_trust)

    async def scenario(caller: Caller) -> None:
        response = await caller.send("POST", "/items/a/set", operation="item_set", resource="a", body={"value": 5})

        assert response.status_code == 500 and response.json() == {"detail": ROUTE_FAILURE_DETAIL}
        assert caller.verified(response, method="POST", operation="item_set", resource="a")

    world.run(scenario)
    assert world.toy.dispatches == {}
