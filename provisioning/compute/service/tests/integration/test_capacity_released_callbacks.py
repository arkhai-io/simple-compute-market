"""The capacity-released callback, delivered by a consumer of
``site.capacity_released``, over the service's typed clients.

Deals are set up through scheduling and ``begin``, which dispatches through the
bare-metal mock; where a test does not step fulfillment convergence it sets the
state convergence would leave. The owning storefront is the double at its
client's transport. Identities are public deterministic development fixtures,
never for a public network.
"""

from __future__ import annotations

from collections.abc import Iterator

import injected_time
import pytest
import pytest_asyncio
from compute_provisioning_ansible import MockAnsibleRunner
from injected_time import InjectedTime
from market_fulfillment import SettlementRecord, SettlementRecordState

from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output
from compute_provisioning_contracts import LeaseForceRelease, LeaseState, LeaseTermination
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.services.deal_event_sink import (
    CAPACITY_RELEASED_CONSUMER,
    capacity_release_request_id,
)

from .bare_metal_deal import begun_bare_metal_deal, create_job_id
from .conftest import SERVICE_SIGNER
from .storefront_peer_double import CAPACITY_RELEASED, LEASE_ENDED, LOST
from .test_leases_api import _committed


@pytest.fixture
def bare_metal_runner():
    return MockAnsibleRunner(default_output=bare_metal_mock_output)


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, held at the wall instant it is installed."""
    before = injected_time.installed()
    installed = InjectedTime()
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


@pytest_asyncio.fixture
async def clients(source, client_and_queue):
    yield client_and_queue[0]


def _status(deliveries):
    (status,) = [
        item for item in deliveries.destinations if item.consumer == CAPACITY_RELEASED_CONSUMER
    ]
    return status


async def test_a_release_delivers_its_callback_under_one_request_identity(
    clients, storefront_peer_double
):
    reservation = _committed("fixture-callback")

    released = await clients.family.force_release_lease(
        reservation, LeaseForceRelease(reason="fixture host inspected")
    )
    await clients.family.force_release_lease(reservation, LeaseForceRelease(reason="retry"))

    (callback,) = storefront_peer_double.taken(CAPACITY_RELEASED)
    lease = await clients.family.get_lease(reservation)
    recorded = _container_module.resolved_capacity_ledger_service.get_reservation(reservation)
    assert callback.body == {
        "capacity_reservation_id": reservation,
        "site_id": "default",
        "released_at": recorded["released_at"],
    }
    assert callback.request_id == capacity_release_request_id(
        reservation, callback.body["released_at"]
    )
    assert (callback.role, callback.signer) == ("service", SERVICE_SIGNER.identity.identifier)
    assert lease.status == LeaseState.FORCE_RELEASED == released.status
    status = _status(await clients.family.get_event_deliveries())
    assert (status.destination, status.delivered, status.pending) == ("storefront", 1, 0)


async def test_a_callback_is_retried_with_backoff_until_acknowledged(
    clients, source, storefront_peer_double
):
    """The release stands whatever the storefront answers; the callback is
    retried, under the same request identity and body, until acknowledged."""
    storefront_peer_double.answer(CAPACITY_RELEASED, 503, LOST)
    reservation = _committed("fixture-callback-retried")

    await clients.family.force_release_lease(
        reservation, LeaseForceRelease(reason="fixture host inspected")
    )
    assert (await clients.family.get_lease(reservation)).status == LeaseState.FORCE_RELEASED
    status = _status(await clients.family.get_event_deliveries())
    assert (status.pending, status.head.attempts) == (1, 1)

    await clients.family.run_event_delivery_cycle()
    assert len(storefront_peer_double.taken(CAPACITY_RELEASED)) == 1

    source.set(injected_time.now() + 11)
    await clients.family.run_event_delivery_cycle()
    source.set(injected_time.now() + 21)
    await clients.family.run_event_delivery_cycle()

    attempts = storefront_peer_double.taken(CAPACITY_RELEASED)
    assert len(attempts) == 3
    assert len({(attempt.request_id, attempt.content) for attempt in attempts}) == 1
    assert _status(await clients.family.get_event_deliveries()).delivered == 1


def _converge(capacity_reservation_id: str, state: SettlementRecordState) -> None:
    """Leave the aggregate where fulfillment convergence would."""
    with _container_module.resolved_session_factory() as db, db.begin():
        db.get(SettlementRecord, capacity_reservation_id).state = state.value


async def test_teardown_completes_after_the_report(clients, storefront_peer_double):
    """The report states the intended end when the lease is terminated; the
    capacity-released callback, acknowledged on its own, follows only once
    teardown completes and the capacity returns."""
    reservation, fulfillment_id = await begun_bare_metal_deal(clients, "escrow-report-first")
    finished = await _container_module.resolved_job_engine.wait_for_terminal(
        create_job_id(reservation), timeout=5.0
    )
    assert finished.status == "succeeded", finished.error
    _converge(reservation, SettlementRecordState.active)

    lease = await clients.family.terminate_lease(reservation, LeaseTermination())

    assert (lease.status, lease.release_job_id) == (LeaseState.RELEASING, fulfillment_id)
    assert [request.resource for request in storefront_peer_double.taken(LEASE_ENDED)] == [
        reservation
    ]
    assert storefront_peer_double.taken(CAPACITY_RELEASED) == []

    _converge(reservation, SettlementRecordState.torn_down)
    await clients.family.check_leases()

    assert (await clients.family.get_lease(reservation)).status == LeaseState.RELEASED
    (callback,) = storefront_peer_double.taken(CAPACITY_RELEASED)
    assert callback.resource == reservation
    assert len(storefront_peer_double.taken(LEASE_ENDED)) == 1
