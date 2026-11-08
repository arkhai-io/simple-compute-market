"""A release that failed on a version-1 connection recovers once the migration runs,
through the typed application clients.

A host stored at ``ssh`` version 1 runs no work, so a lease's teardown against it
fails and the lease waits in ``release_failed``. The migration rewriting stored
version-1 connections to version 2 is what lets the operator's retry-release tear
the deal down, with no force-release. The executor is the bare-metal mock, so these
cases prove the job and lease lifecycle, not a host's cleanup.
"""

from __future__ import annotations

import asyncio

import pytest
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning_contracts import LeaseRetryRelease, LeaseTermination
from sqlalchemy import text

from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output
from compute_provisioning_service.db.migrations import MIGRATIONS

from .bare_metal_deal import HOST_ID, begun_bare_metal_deal, create_job_id
from .test_lease_release_api import (
    _aggregate, _capacity_held, _converge_cycle, _teardown_jobs,
)

_MIGRATION_ID = "20261108_001_ssh_connections_version_2"


@pytest.fixture
def bare_metal_runner():
    return MockAnsibleRunner(default_output=bare_metal_mock_output)


def _store_host_at_version_1(session_factory) -> None:
    """Service-internal setup: the host as the previous release's chain stored
    it, at a version nothing can register any more."""
    with session_factory() as db, db.begin():
        db.execute(
            text("UPDATE hosts SET connection_version = 1 WHERE host_id = :host_id"),
            {"host_id": HOST_ID},
        )


def _run_the_migration(db_engine) -> None:
    (migration,) = [migration for migration in MIGRATIONS if migration.id == _MIGRATION_ID]
    migration.apply(db_engine)


async def test_a_release_failed_on_a_version_1_connection_is_retried_after_migration(
    client_and_queue, test_client, session_factory, db_engine,
):
    clients, queue = client_and_queue
    reservation, _ = await begun_bare_metal_deal(clients, "version-1-release")
    assert (await test_client.wait_for_job(create_job_id(reservation), timeout=5))["status"] == (
        "succeeded"
    )
    await _converge_cycle(clients)
    assert _aggregate(reservation).state == "active"

    # The teardown meets the host at version 1 and fails before any playbook.
    _store_host_at_version_1(session_factory)
    await clients.family.terminate_lease(reservation, LeaseTermination())
    await _converge_cycle(clients)
    (failed,) = _teardown_jobs(reservation)
    assert (await test_client.wait_for_job(failed.id, timeout=5))["status"] == "failed"
    assert "re-register the host at version 2" in (await clients.family.get_job(failed.id)).error
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    await _converge_cycle(clients)
    await clients.family.check_leases()
    assert _aggregate(reservation).state == "teardown_failed"
    assert (await clients.family.get_lease(reservation)).status == "release_failed"
    assert await _capacity_held(clients, reservation)

    _run_the_migration(db_engine)
    assert (await clients.family.get_host(HOST_ID)).connection.version == 2

    await clients.family.retry_lease_release(reservation, LeaseRetryRelease())
    await _converge_cycle(clients)
    retried = [job for job in _teardown_jobs(reservation) if job.id != failed.id]
    assert len(retried) == 1
    assert (await test_client.wait_for_job(retried[0].id, timeout=5))["status"] == "succeeded"
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    await _converge_cycle(clients)
    assert _aggregate(reservation).state == "torn_down"
    assert (await clients.family.check_leases()).released == 1
    assert (await clients.family.get_lease(reservation)).status == "released"
