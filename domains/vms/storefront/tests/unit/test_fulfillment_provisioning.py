"""Unit tests for the storefront-side fulfillment cutover helpers.

Covers ``_fulfillment_result_to_legacy_shape``, ``_poll_fulfillment_until_terminal``,
and ``_connectivity_settings_from_storefront_config`` -- the pure/mockable
pieces of ``_do_provision``'s replacement of the legacy direct-executor-dispatch
path with ``schedule_resource`` -> ``begin_fulfillment`` -> poll status/result.
``_do_provision`` itself uses a real SQLite listing/thread/escrow binding while
the capacity and fulfillment network boundaries remain deterministic doubles.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

# ``alkahest_py`` is a compiled dependency not installed in every
# environment this test may run in; stub it only if genuinely absent, so a
# real environment with the real package is unaffected.
if "alkahest_py" not in sys.modules:
    try:
        import alkahest_py  # noqa: F401
    except ImportError:
        stub = types.ModuleType("alkahest_py")
        stub.AlkahestClient = object
        sys.modules["alkahest_py"] = stub

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arkhai_vms import VmConnectionDetails

from compute_provisioning_client import (
    ComputeProvisioningJobError,
    ComputeProvisioningTimeoutError,
)
from market_core import VersionedEnvelope
from market_storefront.services import fulfillment_service as fs
from market_storefront.services import vm_fulfillment_service as vfs
from tests.fulfillment_fixtures import (
    make_vm_lifecycle_fixture,
    vm_fulfillment_result,
)


class TestFulfillmentResultToConnection:
    def test_the_delivery_becomes_the_deals_connection_details(self):
        envelope = vm_fulfillment_result(
            provisioned_resource_id="res-1",
            credentials=(
                {"role": "root", "password": "root-pw", "key_type": None},
                {"role": "tenant", "password": "tenant-pw", "key_type": "generated"},
            ),
        )

        result = fs._fulfillment_result_to_connection(envelope)

        auth = result.pop("authentication")
        assert VmConnectionDetails.model_validate(result) == VmConnectionDetails(
            host="203.0.113.10",
            port=2222,
            user="tenant1",
            ready_at="2030-01-01T00:00:01+00:00",
            provisioned_resource_ids=("res-1",),
        )
        assert auth == {
            "root": {"password": "root-pw", "key_type": None},
            "tenant": {"password": "tenant-pw", "key_type": "generated"},
        }

    def test_a_result_without_the_access_delivery_is_refused(self):
        envelope = VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={"provisioned_resources": [], "domain_result": None},
        )

        with pytest.raises(RuntimeError, match="unsupported delivery"):
            fs._fulfillment_result_to_connection(envelope)

    def test_an_unknown_credential_role_is_not_kept(self):
        envelope = vm_fulfillment_result(
            credentials=({"role": "admin", "password": "x"},),
        )

        assert "authentication" not in fs._fulfillment_result_to_connection(envelope)


class TestTheStorefrontSelectsNoRelay:
    """The storefront names no relay, on either request-building path.

    Which relay a host dials is recorded on the relay its pool references. A
    storefront naming one per request would make a fleet-wide fact depend on a
    caller's configuration, and would let two requests against one host
    disagree about how that host is reached. The buyer's address and port come
    back in the fulfillment result.
    """

    def test_no_builder_remains_to_be_called(self):
        assert not hasattr(fs, "_connectivity_settings_from_storefront_config")

    def test_neither_request_builder_reads_relay_settings(self):
        """Asserted against the source of both modules rather than by driving
        them, because the point is that no code path exists to reach — a
        behavioural test can only show that the paths exercised did not."""
        import inspect

        from market_storefront.services import vm_fulfillment_service as vfs

        for module in (fs, vfs):
            source = inspect.getsource(module)
            directives = [
                line for line in source.splitlines()
                if not line.lstrip().startswith("#")
            ]
            body = "\n".join(directives)
            for key in ("frp_server_addr", "frp_domain", "frp_dashboard_password"):
                assert key not in body, f"{module.__name__} still reads {key}"


class TestDoProvision:
    """End-to-end coverage of ``_do_provision`` with a mocked fulfillment
    client (real orchestration logic, fake network boundary)."""

    @pytest.fixture
    def fulfillment_client(self):
        client = SimpleNamespace(
            schedule_resource=AsyncMock(return_value=SimpleNamespace(settlement_resource_id="kvm1")),
            begin_fulfillment=AsyncMock(
                return_value=SimpleNamespace(fulfillment_id="fulfillment-1", state="dispatching")
            ),
            get_fulfillment_status=AsyncMock(
                return_value=SimpleNamespace(state="active", failure_message=None)
            ),
            get_fulfillment_result=AsyncMock(
                return_value=vm_fulfillment_result(
                    provisioned_resource_id="res-1",
                )
            ),
        )
        return client

    async def test_schedules_begins_polls_and_returns_result(
        self, monkeypatch, fulfillment_client, tmp_path,
    ):
        lifecycle = await make_vm_lifecycle_fixture(tmp_path / "schedule.db")
        sqlite_client = lifecycle.db
        monkeypatch.setattr(fs, "build_fulfillment_client", lambda *_: fulfillment_client)
        monkeypatch.setattr(fs, "build_capacity_client", lambda *_: SimpleNamespace())
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(
                timeout=5.0, poll_interval=0.001,
            ),
            raising=False,
        )
        job_ids: list[str] = []

        async def _on_job_submitted(job_id: str) -> None:
            job_ids.append(job_id)

        result = await fs._do_provision(
            "ssh-ed25519 AAAA",
            sqlite_client=sqlite_client,
            vm_host="kvm1",
            on_job_submitted=_on_job_submitted,
            capacity_reservation_id="res-1",
            escrow_uid="escrow-1",
        )

        fulfillment_client.schedule_resource.assert_awaited_once()
        schedule_request = fulfillment_client.schedule_resource.await_args.args[0]
        assert schedule_request.capacity_reservation_id == "res-1"
        assert schedule_request.market == "vms"

        assert fulfillment_client.schedule_resource.await_args.kwargs == {
            "site_id": "site-1"
        }
        # Restart-safety persistence: capacity_reservation_id and
        # settlement_resource_id written as soon as scheduling confirms them.
        persisted = await sqlite_client.load_escrow(escrow_uid="escrow-1")
        assert persisted is not None
        assert persisted["capacity_reservation_id"] == "res-1"
        assert persisted["settlement_resource_id"] == "kvm1"
        context = json.loads(persisted["fulfillment_context"])
        assert context["storefront_domain_binding"] == {
            "negotiation_id": "neg-1",
            "listing_id": "listing-1",
            "site_id": "site-1",
            "offering_mode": "vm",
            "domain_identity": "compute.v1",
            "contract_major": 1,
            "contract_minor": 0,
        }

        fulfillment_client.begin_fulfillment.assert_awaited_once()
        begin_body = fulfillment_client.begin_fulfillment.await_args.args[0]
        assert begin_body.capacity_reservation_id == "res-1"
        assert begin_body.market == "vms"
        # Provisioning names the guest; the storefront names nothing else.
        assert begin_body.fulfillment_request.payload == {"ssh_pubkey": "ssh-ed25519 AAAA"}
        assert fulfillment_client.begin_fulfillment.await_args.kwargs == {
            "site_id": "site-1"
        }
        fulfillment_client.get_fulfillment_status.assert_awaited_once_with(
            "fulfillment-1",
            capacity_reservation_id="res-1",
            site_id="site-1",
        )
        fulfillment_client.get_fulfillment_result.assert_awaited_once_with(
            "fulfillment-1",
            capacity_reservation_id="res-1",
            site_id="site-1",
        )

        assert job_ids == ["fulfillment-1"]
        assert (result["host"], result["port"], result["user"]) == ("203.0.113.10", 2222, "tenant1")
        assert "vm_name" not in result
        assert result["provisioned_resource_ids"] == ["res-1"]

    async def test_no_connectivity_is_placed_in_the_request(
        self, monkeypatch, fulfillment_client, tmp_path,
    ):
        """Even with relay-shaped storefront settings present.

        A deployment carrying the removed keys must not quietly resume
        supplying them: the storefront selects no relay, and a leftover setting
        is inert rather than authoritative.
        """
        monkeypatch.setattr(fs, "build_fulfillment_client", lambda *_: fulfillment_client)
        monkeypatch.setattr(fs, "build_capacity_client", lambda *_: SimpleNamespace())
        sqlite_client = (
            await make_vm_lifecycle_fixture(tmp_path / "connectivity.db")
        ).db
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(
                timeout=5.0, poll_interval=0.001,
                frp_server_addr="relay.example.com:7000",
            ),
            raising=False,
        )

        await fs._do_provision(
            "ssh-ed25519 AAAA", vm_host="kvm1",
            sqlite_client=sqlite_client,
            capacity_reservation_id="res-1", escrow_uid="escrow-1",
        )

        begin_body = fulfillment_client.begin_fulfillment.await_args.args[0]
        assert "connectivity" not in begin_body.fulfillment_request.payload

    async def test_failed_state_raises(
        self, monkeypatch, fulfillment_client, tmp_path,
    ):
        fulfillment_client.get_fulfillment_status = AsyncMock(
            return_value=SimpleNamespace(state="failed", failure_message="provisioning failed")
        )
        monkeypatch.setattr(fs, "build_fulfillment_client", lambda *_: fulfillment_client)
        monkeypatch.setattr(fs, "build_capacity_client", lambda *_: SimpleNamespace())
        sqlite_client = (
            await make_vm_lifecycle_fixture(tmp_path / "failure.db")
        ).db
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(
                timeout=5.0, poll_interval=0.001,
            ),
            raising=False,
        )

        with pytest.raises(ComputeProvisioningJobError, match="provisioning failed"):
            await fs._do_provision(
                "ssh-ed25519 AAAA", vm_host="kvm1",
                sqlite_client=sqlite_client,
                capacity_reservation_id="res-1", escrow_uid="escrow-1",
            )
        fulfillment_client.get_fulfillment_result.assert_not_awaited()
    async def test_returns_immediately_on_active(self):
        client = SimpleNamespace(
            get_fulfillment_status=AsyncMock(
                return_value=SimpleNamespace(state="active", failure_message=None)
            )
        )
        status = await fs._poll_fulfillment_until_terminal(
            client, "fulfillment-1", capacity_reservation_id="res-1",
            timeout=5.0, poll_interval=0.01,
            site_id="site-1",
        )
        assert status.state == "active"
        client.get_fulfillment_status.assert_awaited_once_with(
            "fulfillment-1",
            capacity_reservation_id="res-1",
            site_id="site-1",
        )

    async def test_returns_on_failed(self):
        client = SimpleNamespace(
            get_fulfillment_status=AsyncMock(
                return_value=SimpleNamespace(state="failed", failure_message="boom")
            )
        )
        status = await fs._poll_fulfillment_until_terminal(
            client, "fulfillment-1", capacity_reservation_id="res-1",
            timeout=5.0, poll_interval=0.01,
            site_id="site-1",
        )
        assert status.state == "failed"
        assert status.failure_message == "boom"

    async def test_polls_through_non_terminal_states(self):
        states = iter(["assigned", "dispatch_pending", "dispatching", "active"])

        async def _status(*_args, **_kwargs):
            return SimpleNamespace(state=next(states), failure_message=None)

        client = SimpleNamespace(get_fulfillment_status=_status)
        status = await fs._poll_fulfillment_until_terminal(
            client, "fulfillment-1", capacity_reservation_id="res-1",
            timeout=5.0, poll_interval=0.001,
            site_id="site-1",
        )
        assert status.state == "active"

    async def test_raises_timeout_if_never_terminal(self):
        client = SimpleNamespace(
            get_fulfillment_status=AsyncMock(
                return_value=SimpleNamespace(state="dispatching", failure_message=None)
            )
        )
        with pytest.raises(ComputeProvisioningTimeoutError):
            await fs._poll_fulfillment_until_terminal(
                client, "fulfillment-1", capacity_reservation_id="res-1",
                timeout=0.02, poll_interval=0.01,
                site_id="site-1",
            )


class TestPersistEscrowFieldsWithRetry:
    """Persistence must not be a single silent attempt: retry a bounded
    number of times, and escalate loudly (ERROR, not WARNING) if every
    attempt fails, rather than swallowing the failure -- a failed write
    here reopens the orphaned-work window this persistence exists to
    close."""

    async def test_succeeds_on_first_attempt(self):
        sqlite_client = SimpleNamespace(update_escrow=AsyncMock())
        ok = await vfs.persist_escrow_fields_with_retry(
            lambda: sqlite_client, escrow_uid="escrow-1", fulfillment_id="f-1",
        )
        assert ok is True
        sqlite_client.update_escrow.assert_awaited_once_with(
            escrow_uid="escrow-1", fulfillment_id="f-1",
        )

    async def test_retries_and_succeeds(self):
        sqlite_client = SimpleNamespace(
            update_escrow=AsyncMock(
                side_effect=[RuntimeError("db locked"), RuntimeError("db locked"), None]
            )
        )
        ok = await vfs.persist_escrow_fields_with_retry(
            lambda: sqlite_client, escrow_uid="escrow-1", fulfillment_id="f-1",
            backoff_seconds=0.001,
        )
        assert ok is True
        assert sqlite_client.update_escrow.await_count == 3

    async def test_gives_up_after_bounded_attempts_and_logs_error(self, caplog):
        sqlite_client = SimpleNamespace(
            update_escrow=AsyncMock(side_effect=RuntimeError("db locked"))
        )
        with caplog.at_level("ERROR"):
            ok = await vfs.persist_escrow_fields_with_retry(
                lambda: sqlite_client, escrow_uid="escrow-1", fulfillment_id="f-1",
                attempts=3, backoff_seconds=0.001,
            )
        assert ok is False
        assert sqlite_client.update_escrow.await_count == 3
        assert any(
            "Failed to persist" in record.message and "escrow-1" in record.message
            for record in caplog.records
        )
        assert any(record.levelname == "ERROR" for record in caplog.records)


@pytest.mark.asyncio
async def test_the_storefront_names_no_guest_and_writes_the_lease_only_at_commit(
    monkeypatch,
    tmp_path,
):
    """Provisioning names the guest from the capacity reservation, so the
    storefront records, sends, and registers without one; it learns the
    delivery afterwards."""

    plan = SimpleNamespace(
        order_id="listing-1",
        required_attributes={"vcpu_count": 2},
    )
    monkeypatch.setattr(vfs, "build_vm_fulfillment_plan", lambda **_: plan)

    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "no-guest-name.db")
    sqlite_client = lifecycle.db

    async def capacity_binding_for_listing(repository, listing_id):
        assert repository is sqlite_client
        assert listing_id == lifecycle.thread_binding.listing_id
        return lifecycle.capacity_binding

    monkeypatch.setattr(
        "market_storefront.services.capacity_client.capacity_binding_for_listing",
        capacity_binding_for_listing,
    )
    capacity = SimpleNamespace(
        reserve=AsyncMock(return_value={
            "capacity_reservation_id": "reservation-1",
            "resource_id": "resource-1",
            "site": "site-1",
        }),
        commit=AsyncMock(return_value={
            "capacity_reservation_id": "reservation-1",
            "state": "leased",
            "lease_start_utc": "2026-01-01T00:00:00+00:00",
            "lease_end_utc": "2026-01-01 01:00",
        }),
    )
    observed: dict[str, dict] = {}

    async def provision_vm(ssh_public_key: str, *, on_job_submitted, **kwargs) -> dict:
        observed["provision"] = kwargs
        observed["commits_before_provisioning"] = capacity.commit.await_count
        await on_job_submitted("fulfillment-1")
        return {"authentication": {}}

    result = await vfs.fulfill_vm_obligation(
        client=None,
        escrow_uid="escrow-1",
        ssh_public_key="ssh-ed25519 test",
        order={"listing_id": "listing-1"},
        listing_id="listing-1",
        site_id="site-1",
        get_sqlite_client=lambda: sqlite_client,
        capacity=capacity,
        stage_event=lambda *args, **kwargs: None,
        provision_vm=provision_vm,
    )
    await asyncio.sleep(0)

    persisted = await sqlite_client.load_escrow(escrow_uid="escrow-1")
    assert persisted is not None
    context = json.loads(persisted["fulfillment_context"])
    assert context["payload"]["fulfillment_request"]["payload"] == {
        "ssh_pubkey": "ssh-ed25519 test"
    }
    assert capacity.reserve.await_args.args == (lifecycle.capacity_binding,)
    assert "vm_target" not in observed["provision"]
    # The lease begins at the one commit before provisioning, which records
    # the deal's escrow; nothing writes the lease afterwards.
    assert observed["commits_before_provisioning"] == capacity.commit.await_count == 1
    assert capacity.commit.await_args.kwargs["deal_ref"] == {"escrow_uid": "escrow-1"}
    assert result["status"] == "fulfilled"


@pytest.mark.asyncio
async def test_the_commit_does_not_require_resource_id(
    monkeypatch,
    tmp_path,
):
    """Regression test for the opaque-reservation gap.

    ``kit/site``'s ``/reservations`` endpoint strips ``resource_id``,
    ``capacity_bucket_id``, and ``backing_resource_id`` from every
    reservation response -- the capacity boundary negotiates on pooled
    capacity, not a pinned physical resource, so ``reserve()`` legitimately
    returns without them. The previous test above exercises a ``reserve()``
    double that (unrealistically) still supplies ``resource_id``/``vm_host``,
    so it cannot catch a regression where the commit that begins the lease is
    gated on those fields being present. This test uses the real, opaque
    shape and asserts the commit still fires.
    """
    plan = SimpleNamespace(
        order_id="listing-1",
        required_attributes={"vcpu_count": 2},
    )
    monkeypatch.setattr(vfs, "build_vm_fulfillment_plan", lambda **_: plan)

    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "opaque-reservation.db")
    sqlite_client = lifecycle.db

    async def capacity_binding_for_listing(repository, listing_id):
        assert repository is sqlite_client
        assert listing_id == lifecycle.thread_binding.listing_id
        return lifecycle.capacity_binding

    monkeypatch.setattr(
        "market_storefront.services.capacity_client.capacity_binding_for_listing",
        capacity_binding_for_listing,
    )
    capacity = SimpleNamespace(
        reserve=AsyncMock(return_value={
            "capacity_reservation_id": "reservation-1",
            # No resource_id/vm_host -- the real opaque-reservation shape.
            "site": "site-1",
        }),
        commit=AsyncMock(return_value={
            "capacity_reservation_id": "reservation-1",
            "state": "leased",
            "lease_start_utc": "2026-01-01T00:00:00+00:00",
            "lease_end_utc": "2026-01-01 01:00",
        }),
    )

    async def provision_vm(
        ssh_public_key: str, *, on_job_submitted, **_: object,
    ) -> dict[str, object]:
        await on_job_submitted("fulfillment-1")
        return {"authentication": {}}

    result = await vfs.fulfill_vm_obligation(
        client=None,
        escrow_uid="escrow-1",
        ssh_public_key="ssh-ed25519 test",
        order={"listing_id": "listing-1"},
        listing_id="listing-1",
        site_id="site-1",
        get_sqlite_client=lambda: sqlite_client,
        capacity=capacity,
        stage_event=lambda *args, **kwargs: None,
        provision_vm=provision_vm,
    )
    await asyncio.sleep(0)

    assert result["status"] == "fulfilled"
    assert capacity.reserve.await_args.args == (lifecycle.capacity_binding,)
    capacity.commit.assert_awaited_once()
    commit = capacity.commit.await_args
    assert commit.kwargs["capacity_reservation_id"] == "reservation-1"
    assert commit.kwargs["resource_id"] is None


_RECORDED_WINDOW = {
    "capacity_reservation_id": "reservation-1",
    "state": "leased",
    "lease_start_utc": "2026-01-01T00:00:00+00:00",
    "lease_end_utc": "2026-01-01 01:00",
}


async def _fulfil_after_provisioning(monkeypatch, tmp_path, *, commit):
    """Run the VM main path to past provisioning with the given commit; the VM
    itself is always provisioned."""
    plan = SimpleNamespace(order_id="listing-1", required_attributes={"vcpu_count": 2})
    monkeypatch.setattr(vfs, "build_vm_fulfillment_plan", lambda **_: plan)
    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "deferral.db")
    sqlite_client = lifecycle.db

    async def capacity_binding_for_listing(repository, listing_id):
        return lifecycle.capacity_binding

    monkeypatch.setattr(
        "market_storefront.services.capacity_client.capacity_binding_for_listing",
        capacity_binding_for_listing,
    )
    capacity = SimpleNamespace(
        reserve=AsyncMock(return_value={"capacity_reservation_id": "reservation-1", "site": "site-1"}),
        commit=commit,
    )
    provisioned: list[str] = []

    async def provision_vm(ssh_public_key, *, on_job_submitted, **_):
        await on_job_submitted("fulfillment-1")
        provisioned.append(ssh_public_key)
        return {"authentication": {}}

    result = await vfs.fulfill_vm_obligation(
        client=None,
        escrow_uid="escrow-1",
        ssh_public_key="ssh-ed25519 test",
        order={"listing_id": "listing-1"},
        listing_id="listing-1",
        site_id="site-1",
        get_sqlite_client=lambda: sqlite_client,
        capacity=capacity,
        stage_event=lambda *args, **kwargs: None,
        provision_vm=provision_vm,
    )
    await asyncio.sleep(0)
    assert provisioned, "the VM was provisioned"
    return result


@pytest.mark.asyncio
async def test_a_failed_evidence_publication_after_provisioning_is_deferred(
    monkeypatch, tmp_path
):
    """Publishing the fulfillment is retried by the resume pass rather than
    failing a deal whose VM is running."""
    monkeypatch.setattr(
        vfs, "submit_compute_fulfillment", AsyncMock(side_effect=RuntimeError("rpc down"))
    )

    result = await _fulfil_after_provisioning(
        monkeypatch,
        tmp_path,
        commit=AsyncMock(return_value=_RECORDED_WINDOW),
    )

    assert result["status"] == "deferred"
    assert "evidence publication" in result["message"]
