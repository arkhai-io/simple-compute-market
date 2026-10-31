"""Compute-family helpers for complete-deal scenarios.

What lives here is the compute family's, not one domain's: the storefront loop
controls every storefront binds, the provisioning service's mock-rule and
fulfillment-convergence controls, and the lease view over the site ledger and
the family lease contract. Nothing here reads a lane's settings; each scenario's
conftest supplies the clients, signers, and trust pins its lane configures.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from market_site_client import SiteCapacityClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storefront lifecycle loops
# ---------------------------------------------------------------------------

def advance_storefront(storefront_admin_client, loop: str) -> dict:
    """Run one cycle of a paused storefront loop and return what it reports.

    `loop` is the loop's route name, such as `settlement-servicing`,
    `capacity-events`, or `site-projections`. Each calls the operation the
    timer was already invoking, so a stage advances production behaviour rather
    than a test-only path.

    This is the other half of `storefront_loops_held`. Holding without
    advancing just stops the system; the pair is what makes ordering assertable -- a
    stage asks for the work it is about to assert on, instead of racing a timer
    that may or may not have run.
    """
    result = storefront_admin_client.admin_run_lifecycle_cycle(loop)
    log.info("[lifecycle] advanced %s: %s", loop, result)
    return result


def dry_run_storefront(storefront_admin_client, loop: str) -> dict:
    """Report what one cycle of a paused loop would do, without doing it.

    The read half of `advance_storefront`. A reconciliation cycle closes and
    reopens listings, so advancing changes what buyers can discover; asking
    first is what lets a stage assert the cause separately from the effect,
    instead of asserting the effect and inferring the cause.
    """
    result = storefront_admin_client.admin_dry_run_lifecycle_cycle(loop)
    log.info("[lifecycle] dry-run %s: %s", loop, result)
    return result


# A scenario that needs a shared service's timer held -- a storefront's
# lifecycle loops, provisioning's fulfillment convergence or lease watchdog --
# takes its lane's hold fixture for the whole module with `usefixtures`, listed
# first. Each fixture is one of the helpers below: the hold is taken before the
# module's first stage, waits until every held loop reports itself at its gate,
# and is released in a `finally` whatever the module's outcome. Stages assert a
# hold; they never pause or resume a service themselves, which
# `tests/unit/test_scenario_holds.py` checks from source. A module killed by
# `helm test`'s timeout runs no finaliser, and only a restart clears its pause.

#: How long a hold waits for a cycle that began before the pause to finish.
HOLD_TIMEOUT_SECONDS = 60.0
_HOLD_POLL_SECONDS = 0.5


def _until_held(
    pause,
    held,
    describe: str,
    *,
    timeout: float = HOLD_TIMEOUT_SECONDS,
    clock=time.monotonic,
    sleep=time.sleep,
) -> Any:
    """Repeat ``pause`` until ``held`` accepts what it answers.

    A pause is idempotent and answers the loops' gate state as it stands, so
    repeating it reads that state afresh. A loop running a cycle that began
    before the pause reaches its gate once the cycle ends; the wait is bounded
    so a loop that never does fails the hold instead of hanging the module.
    """
    deadline = clock() + timeout
    while True:
        answer = pause()
        if held(answer):
            return answer
        if clock() >= deadline:
            raise AssertionError(
                f"{describe} did not reach its gate within {timeout:.0f}s: "
                f"{answer!r}. A stage run now would race the cycle still going."
            )
        sleep(_HOLD_POLL_SECONDS)


def _storefront_loops_at_gate(answer: dict) -> bool:
    assert answer.get("paused") is True, (
        f"the storefront did not report its loops paused: {answer!r}"
    )
    loops = answer.get("loops") or {}
    assert loops, f"the storefront registered no loop to hold: {answer!r}"
    return all(state == "paused" for state in loops.values())


@contextmanager
def storefront_loops_held(storefront_admin_client) -> Iterator[dict]:
    """Hold a storefront's lifecycle loops for a module, and release them after.

    Pauses the loops only -- trading stays open, so a held module still agrees
    deals -- and yields once every loop reports itself paused at its gate, so
    each cycle a stage observes is one the stage asked for (`advance_storefront`)
    rather than one racing a timer. Resumed in the `finally`, which also covers
    a hold that never reached its gate -- the pause was already sent -- so
    neither a failing stage nor a failed hold leaves the next module with the
    loops stopped. See the module-hold rule above.
    """
    try:
        held = _until_held(
            storefront_admin_client.admin_pause_lifecycle_loops,
            _storefront_loops_at_gate,
            "a storefront lifecycle loop",
        )
        log.info("[hold] storefront loops held: %s", held.get("loops"))
        yield held
    finally:
        storefront_admin_client.admin_resume_lifecycle_loops()
        log.info("[hold] storefront loops resumed")


def assert_storefront_loops_held(storefront_admin_client) -> dict:
    """The module's storefront hold, read back through system status: every
    timed loop paused. What a stage asserts instead of pausing.

    A loop registered as a step alone runs no timer and reports no state, so
    there is nothing of it to hold; the pause answer leaves it out the same way.
    """
    lifecycle = storefront_admin_client.get_system_status().lifecycle or {}
    timed = {name: loop for name, loop in lifecycle.items() if loop.get("state") is not None}
    assert timed, f"the storefront reports no timed lifecycle loop: {lifecycle}"
    running = {name: loop.get("state") for name, loop in timed.items() if loop.get("state") != "paused"}
    assert not running, (
        f"these storefront loops are not held: {running}. The module takes its "
        "lane's storefront hold fixture with `usefixtures`."
    )
    return lifecycle


@contextmanager
def fulfillment_convergence_held(provisioning_client) -> Iterator[Any]:
    """Hold fulfillment convergence's timer for a module, and release it after.

    For a module that advances convergence itself: every convergence transition
    it asserts is triggered by an explicit advance. A timer cycle that claimed a
    row while its provider call was still gated would hold the claim lease, and
    the stage's own cycle would then reach nothing at all. Yields once the
    watchdog is at its gate; a failed pause fails the hold. Resumed in the
    `finally`, which also covers a hold that never reached its gate, since the
    provisioning service is shared across modules. See the module-hold rule
    above.
    """
    try:
        held = _until_held(
            provisioning_client.pause_fulfillment_convergence,
            lambda answer: answer.at_gate,
            "fulfillment convergence",
        )
        log.info("[hold] fulfillment convergence held")
        yield held
    finally:
        provisioning_client.resume_fulfillment_convergence()
        log.info("[hold] fulfillment convergence resumed")


@contextmanager
def lease_watchdog_held(provisioning_client) -> Iterator[Any]:
    """Hold the lease watchdog's timer for a module, and release it after.

    For a module that steps lease expiry itself (`check_leases`): with the
    timer held, an expiry a stage back-dates sits unobserved until the stage
    runs one cycle, so trigger and reaction are separate, asserted steps.
    Yields the watchdog's pause state once it is at its gate; resumed in the
    `finally`, which also covers a hold that never reached its gate. Stages
    read the hold back with `assert_lease_watchdog_held`. See the module-hold
    rule above.
    """
    try:
        held = _until_held(
            provisioning_client.pause_lease_watchdog,
            lambda answer: answer.at_gate,
            "the lease watchdog",
        )
        log.info("[hold] lease watchdog held")
        yield held
    finally:
        provisioning_client.resume_lease_watchdog()
        log.info("[hold] lease watchdog resumed")


def assert_lease_watchdog_held(provisioning_client) -> None:
    """The module's lease-watchdog hold, read back through system status.

    What a stage that steps lease expiry asserts instead of pausing: a module
    that reused such a stage without taking the hold fails here rather than
    racing the watchdog's timer.
    """
    checks = provisioning_client.get_system_status().checks
    assert checks.get("lease_watchdog") == "paused", (
        f"the lease watchdog is not held: {checks.get('lease_watchdog')!r}. The "
        "module takes its lane's `lease_watchdog_held` fixture with `usefixtures`."
    )


def wait_for_stage_event(
    client,
    stage: str,
    event: str,
    *,
    listing_id: str | None = None,
    negotiation_id: str | None = None,
    since_id: int = 0,
    timeout: float = 30.0,
):
    """Block until the matching stage event appears in /api/v1/system/events.

    Wraps ``SyncStorefrontClient.wait_for_stage_event`` with a friendlier
    pytest-style timeout error message.

    Parameters
    ----------
    client:
        A ``SyncStorefrontClient`` asserting the ``admin`` role.
    stage, event:
        Stage and event strings to match (e.g. ``"discovery"``, ``"order_published"``).
    listing_id, negotiation_id:
        Optional filters passed through to the events query.
    since_id:
        Ignore events older than this id. Use when waiting for the
        *next* event after triggering an action — snapshot the latest
        id via ``get_events`` first, then pass it here.
    timeout:
        Seconds to wait before raising AssertionError.
    """
    try:
        return client.wait_for_stage_event(
            stage, event,
            listing_id=listing_id,
            negotiation_id=negotiation_id,
            since_id=since_id,
            timeout=timeout,
        )
    except TimeoutError as exc:
        pytest.fail(str(exc))


def latest_stage_event_id(client, *, negotiation_id: str) -> int:
    """The id of the latest stage event naming ``negotiation_id``, or 0.

    A ``since_id`` mark for ``wait_for_stage_event``, taken before the action
    whose event the wait is for. It counts only that negotiation's events, so
    an event the wait finds came after the action only when the wait filters
    by the same negotiation. Read page by page: a page holds the oldest events
    after its cursor, and only the storefront can say whether more follow it.
    """
    mark = 0
    while True:
        page = client.get_events(since_id=mark, limit=500, negotiation_id=negotiation_id)
        mark = max((event.id for event in page.events), default=mark)
        if not page.truncated or not page.events:
            return mark


# ---------------------------------------------------------------------------
# Provisioning mock rules and fulfillment convergence
# ---------------------------------------------------------------------------

def delete_mock_rules_if_present(rules, *rule_ids: str) -> None:
    """Best-effort cleanup for stateful provisioning mock rules.

    ``rules`` is one domain's mock-rule client, as the provisioning test
    client offers it (``vm_rules``, ``bare_metal_rules``). The mock-rule
    service preserves insertion order. When multiple e2e scenarios run in one
    pytest process against one stack, a stale broad create rule can match
    before the rule that the current scenario just armed. Delete known
    scenario rule ids before arming a new rule so each scenario controls its
    own evaluation order.
    """
    for rule_id in rule_ids:
        try:
            rules.delete_rule(rule_id)
        except Exception as exc:
            log.debug("Could not delete mock rule %s: %s", rule_id, exc)


def advance_fulfillment_to(
    provisioning_client,
    fulfillment_id: str,
    expected: str,
    *,
    max_advances: int = 4,
) -> dict:
    """Advance convergence until a fulfillment reaches ``expected``.

    No sleeps, per `docs/development/TESTING.md`'s async test discipline:
    each iteration is one *explicit* advance, and the only thing between
    iterations is a request the test made.

    `advance-cycle` rather than `run-cycle` because `run-cycle` is an
    advance attempt, not an advance. The pending branches of the
    convergence watchdog deliberately leave their claim in place so the
    claim lease spaces the next provider poll, and `claim_pending` skips a
    row whose lease has not lapsed -- 5s for the first claim, doubling
    after. So a `run-cycle` issued straight after a pending poll cannot
    touch the row, and any number of them in that window is still zero
    advances. `advance-cycle` releases the watchdog's own claims first.

    Requires the convergence watchdog to be held (see
    `fulfillment_convergence_held`), which is also what stops the timer from
    claiming the same rows mid-scenario.

    ``max_advances`` is small deliberately: with the timer stopped and the
    provider gate released, each transition needs exactly one advance, so
    needing several means something is wrong and the failure names the
    state it stalled in.
    """
    last: dict = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
    for _ in range(max_advances):
        if last.get("state") == expected:
            return last
        provisioning_client.advance_fulfillment_convergence_cycle()
        last = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
    if last.get("state") != expected:
        pytest.fail(
            f"fulfillment {fulfillment_id} did not reach {expected!r} within "
            f"{max_advances} explicit convergence advances; last state "
            f"{last.get('state')!r}: {last}"
        )
    return last


# ---------------------------------------------------------------------------
# The lease view: the site ledger and the family lease contract
# ---------------------------------------------------------------------------

class SiteCapacity:
    """A site's capacity reads and lease truncation, from a sync scenario.

    Drives the canonical async ``SiteCapacityClient``, one ``asyncio.run`` per
    call. The caller supplies the site's URL, the signer it authenticates as,
    and the site's pinned signing principal; only call shape lives here.
    """

    def __init__(self, url: str, signer: Any, trust: Any, *, caller_role: str = "admin") -> None:
        self._url = url
        self._signer = signer
        self._trust = trust
        self._caller_role = caller_role

    def _client(self) -> SiteCapacityClient:
        return SiteCapacityClient(
            self._url, self._signer, self._trust, caller_role=self._caller_role
        )

    def snapshot(self) -> list[dict]:
        return asyncio.run(self._client().snapshot())

    def list_reservations(self, *, state: str | None = None, escrow_uid: str | None = None) -> list[dict]:
        return asyncio.run(self._client().list_reservations(state=state, escrow_uid=escrow_uid))

    def reservations_for_negotiation(self, negotiation_id: str) -> list[dict]:
        """Reservations a deal holds, found by the deal reference its hold names.

        VM delivery holds and commits capacity under the deal's negotiation,
        whatever its settlement mechanism, so a VM deal settled through escrow
        has no escrow on its reservation.
        """
        return [
            reservation
            for reservation in self.list_reservations()
            if (reservation.get("deal_ref") or {}).get("negotiation_id") == negotiation_id
        ]

    def get_reservation(self, capacity_reservation_id: str) -> dict:
        return asyncio.run(self._client().get_reservation(capacity_reservation_id)) or {}

    def reserve(self, *, claim: dict, deal_ref: dict) -> dict | None:
        return asyncio.run(self._client().reserve(claim=claim, deal_ref=deal_ref))

    def release(self, capacity_reservation_id: str) -> dict | None:
        """Release one reservation at the site, as its own lifecycle would."""
        return asyncio.run(
            self._client().release(capacity_reservation_id=capacity_reservation_id)
        )

    def truncate_lease(self, capacity_reservation_id: str, lease_end_utc: str) -> dict | None:
        """End a leased reservation's lease early; ``None`` if the site refuses."""
        return asyncio.run(
            self._client().truncate_lease(
                capacity_reservation_id=capacity_reservation_id,
                lease_end_utc=lease_end_utc,
            )
        )


class DealLease:
    """One deal's lease: the temporal tail of its ledger reservation.

    The full-deal scenarios drive the expiry lifecycle through this
    view — resolve the reservation by the deal reference its hold names (the
    negotiation for VM, the escrow for bare metal), read it back in lease
    vocabulary, back-date its end, and observe the watchdog release it
    in the ledger with a deal-scoped capacity-released event to the
    storefront.

    ``status`` and ``release_job_id`` come from the compute family's lease
    contract, read through the family client. ``release_job_id`` is the
    durable fulfillment id: release goes through the fulfillment aggregate.
    The lease's end moves only through the site's truncation, which is how
    the scenario back-dates it.
    """

    def __init__(
        self,
        provisioning_client,
        site_capacity: SiteCapacity,
        *,
        negotiation_id: str | None = None,
        escrow_uid: str | None = None,
    ) -> None:
        if (negotiation_id is None) == (escrow_uid is None):
            raise ValueError("a deal's lease is found by its negotiation or its escrow")
        self._leases = provisioning_client
        self._site = site_capacity
        self.is_ledger = True
        if negotiation_id is not None:
            self.deal_field, self.deal_value = "negotiation_id", negotiation_id
            reservations = self._site.reservations_for_negotiation(negotiation_id)
        else:
            self.deal_field, self.deal_value = "escrow_uid", str(escrow_uid)
            reservations = self._site.list_reservations(escrow_uid=escrow_uid)
        live = [a for a in reservations if a.get("lease_end_utc")]
        assert live, (
            f"No ledger reservation with a lease tail for {self.deal_field} "
            f"{self.deal_value!r} — was the deal's hold committed into a lease?"
        )
        self.lease_id = str(live[0]["capacity_reservation_id"])

    def refresh(self) -> dict:
        """Current lease fields from the public compute lease contract."""
        lease = self._leases.get_lease(self.lease_id)
        row = self._site.get_reservation(self.lease_id)
        data = lease.model_dump(mode="json")
        deal_ref = row.get("deal_ref") or {}
        return {
            "id": data.get("capacity_reservation_id") or self.lease_id,
            "negotiation_id": deal_ref.get("negotiation_id"),
            "escrow_uid": row.get("escrow_uid") or deal_ref.get("escrow_uid"),
            "resource_id": row.get("resource_id"),
            "host_id": row.get("host_id"),
            "executor_target": data.get("executor_target"),
            "status": data.get("status"),
            "fulfillment_id": data.get("release_job_id"),
            "create_job_id": data.get("create_job_id"),
        }

    def backdate(self, lease_end_utc: str) -> dict:
        """Move the lease end into the past so the next watchdog cycle fires.

        Truncates the lease at the site: truncation is the only operation that
        moves a lease's end, and only earlier. Returns the refreshed normalized
        lease view.
        """
        truncated = self._site.truncate_lease(self.lease_id, lease_end_utc)
        assert truncated is not None, (
            f"the site refused to truncate lease {self.lease_id!r} to {lease_end_utc!r}"
        )
        return self.refresh()

    def resource_consumed(self, storefront_admin_client, resource_id: str) -> bool:
        """Whether the deal's capacity is still held, per the ledger.

        Read from the site's mirror dimension where the declaration states it.
        A declaration without it, such as a machine with no GPUs, has no scalar
        total, so its capacity is held while any dimension it declares has less
        available than declared.
        """
        for row in self._site.snapshot():
            if str(row.get("resource_id")) == resource_id:
                if row.get("value") is not None:
                    return int(row.get("available_units") or 0) < int(row["value"])
                declared = row.get("capacity") or {}
                available = row.get("available") or {}
                assert declared, f"Resource {resource_id!r} declares no capacity: {row}"
                return any(available.get(name, 0) < amount for name, amount in declared.items())
        pytest.fail(
            f"Resource {resource_id!r} not found in site capacity snapshot"
        )

    @property
    def released_stage_event(self) -> tuple[str, str]:
        """(stage, event) the storefront emits when this lease releases."""
        return ("fulfillment", "capacity_released")
