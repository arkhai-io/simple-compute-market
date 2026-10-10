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
from collections.abc import Iterator
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

    This is the other half of `pause_storefront`. Pausing without advancing
    just stops the system; the pair is what makes ordering assertable -- a
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


def pause_storefront(storefront_admin_client) -> bool:
    """Hold the storefront's timer loops idle, and prove they are.

    Pauses the loops only -- trading stays open, so a scenario can pause at its
    readiness stage and still agree a deal.

    Called from a scenario's own stage rather than an autouse fixture: a
    scenario should name the state it depends on, and pausing a service is a
    dependency as much as registering a host is.

    Every side effect a scenario asserts on should be one the scenario asked
    for. While the timer loops run, a stage's observation races them: a listing
    reconciled a second later reads differently than one reconciled a second
    earlier. Waiting for the system to settle instead is what
    `docs/development/TESTING.md` forbids, and it cannot establish ordering
    even when it passes.

    The response names each loop's gate state, which is what lets this assert
    that the loop a scenario depends on actually reached its gate rather than
    merely that a pause was requested.
    """
    result = storefront_admin_client.admin_pause_lifecycle_loops()
    assert result.get("paused") is True, (
        f"storefront did not report its loops paused: {result!r}. An "
        "assertion made now would race the timer loops it was meant to hold."
    )
    loops = result.get("loops") or {}
    not_at_gate = {
        name: state for name, state in loops.items() if state != "paused"
    }
    assert loops and not not_at_gate, (
        f"these loops had not reached a gate when the pause returned: "
        f"{not_at_gate or 'none registered'}. `running` means a cycle that "
        "began before the request is still going, so an assertion made now "
        "would race it."
    )
    log.info("[lifecycle] storefront loops paused; loops=%s", loops)
    return True


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


# ---------------------------------------------------------------------------
# Provisioning mock rules and fulfillment convergence
# ---------------------------------------------------------------------------

def delete_mock_rules_if_present(provisioning_test_client, *rule_ids: str) -> None:
    """Best-effort cleanup for stateful provisioning mock rules.

    The mock-rule service preserves insertion order. When multiple e2e
    scenarios run in one pytest process against one stack, a stale broad
    create rule can match before the rule that the current scenario just
    armed. Delete known scenario rule ids before arming a new rule so each
    scenario controls its own evaluation order.
    """
    for rule_id in rule_ids:
        try:
            provisioning_test_client.delete_mock_rule(rule_id)
        except Exception as exc:
            log.debug("Could not delete mock rule %s: %s", rule_id, exc)


def convergence_paused(provisioning_client) -> Iterator[None]:
    """Hold fulfillment convergence's timer for a module that advances it itself.

    The body of each conftest's opt-in ``convergence_advanced_explicitly``
    fixture, taken with ``pytest.mark.usefixtures`` by the modules that drive
    convergence. Deliberately not autouse: other scenarios reach ``active`` on
    the timer without ever asking for a cycle, and pausing it for them would
    stall their fulfillment instead of making it deterministic.

    Every convergence transition such a module asserts is triggered by an
    explicit advance, so the timer is stopped for the duration. Leaving it
    running made those stages races rather than steps: a timer cycle that
    claimed a row while its provider call was still gated would hold the claim
    lease, and the stage's own cycle would then reach nothing at all.

    Resumed when the generator closes, so it is restored even when a stage
    fails. That matters because the provisioning service is shared across
    scenario modules, and leaving convergence paused would stall the next
    module's fulfillment rather than this one's.
    """
    try:
        paused = provisioning_client.pause_fulfillment_convergence()
        log.info("[setup] Fulfillment convergence timer paused: %s", paused)
    except Exception as exc:
        log.warning("[setup] Could not pause fulfillment convergence: %s", exc)
    try:
        yield
    finally:
        try:
            provisioning_client.resume_fulfillment_convergence()
        except Exception as exc:
            log.warning(
                "[teardown] Could not resume fulfillment convergence: %s", exc
            )


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

    Requires the convergence watchdog to be paused (see
    `convergence_paused`), which is also what stops the timer from claiming
    the same rows mid-scenario.

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
        """Whether the deal's capacity is still held, per the ledger."""
        for row in self._site.snapshot():
            if str(row.get("resource_id")) == resource_id:
                total = int(row.get("value") or 0)
                return int(row.get("available_units") or 0) < total
        pytest.fail(
            f"Resource {resource_id!r} not found in site capacity snapshot"
        )

    @property
    def released_stage_event(self) -> tuple[str, str]:
        """(stage, event) the storefront emits when this lease releases."""
        return ("fulfillment", "capacity_released")
