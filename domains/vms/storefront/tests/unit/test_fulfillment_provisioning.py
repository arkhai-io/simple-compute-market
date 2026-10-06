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

from compute_provisioning import ComputeProvisioningTimeoutError
from market_fulfillment import VersionedEnvelope
from market_storefront.services import fulfillment_service as fs
from market_storefront.services import vm_fulfillment_service as vfs
from tests.fulfillment_fixtures import (
    make_vm_lifecycle_fixture,
    vm_fulfillment_result,
)


class TestFulfillmentResultToLegacyShape:
    def test_maps_root_and_tenant_credentials(self):
        envelope = VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={
                "provisioned_resources": [{"provisioned_resource_id": "res-1", "status": "active"}],
                "domain_result": {
                    "kind": "vm.fulfillment.result.v1",
                    "schema_version": 1,
                    "payload": {
                        "connection_info": {
                            "vm_name": "agent-vm-01",
                            "host": "kvm1",
                            "timestamp": "2026-07-26T00:00:00Z",
                            "tenant_user": "mockuser",
                            "vm_ip_internal": "192.168.122.2",
                            "ssh_port": "2222",
                        },
                        "credentials": [
                            {
                                "role": "root",
                                "password": "root-pw",
                                "ssh_commands": {"internal": "ssh root@192.168.122.2"},
                                "ssh_key_path_host": "/root/.ssh/id_ed25519",
                                "provisioned_resource_ids": ["res-1"],
                            },
                            {
                                "role": "tenant",
                                "password": "tenant-pw",
                                "ssh_commands": {"external": "ssh -p 2222 mockuser@127.0.0.1"},
                                "key_type": "generated",
                                "provisioned_resource_ids": ["res-1"],
                            },
                        ],
                    },
                },
            },
        )

        result = fs._fulfillment_result_to_legacy_shape(envelope)

        assert result["vm_name"] == "agent-vm-01"
        assert result["host"] == "kvm1"
        assert result["vm_ip_internal"] == "192.168.122.2"
        assert result["ssh_port"] == "2222"
        assert result["provisioned_resource_ids"] == ["res-1"]

        auth = result["authentication"]
        assert auth["root"]["password"] == "root-pw"
        assert auth["root"]["ssh_key_path_host"] == "/root/.ssh/id_ed25519"
        assert "key_type" not in auth["root"]
        assert auth["tenant"]["password"] == "tenant-pw"
        assert auth["tenant"]["key_type"] == "generated"
        assert "ssh_key_path_host" not in auth["tenant"]

    def test_no_domain_result_means_no_authentication_key(self):
        envelope = VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={"provisioned_resources": [], "domain_result": None},
        )

        result = fs._fulfillment_result_to_legacy_shape(envelope)

        assert "authentication" not in result
        assert result["provisioned_resource_ids"] == []
        assert result.get("vm_name") is None

    def test_unknown_credential_role_is_ignored(self):
        envelope = VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={
                "provisioned_resources": [],
                "domain_result": {
                    "kind": "vm.fulfillment.result.v1",
                    "schema_version": 1,
                    "payload": {
                        "credentials": [
                            {"role": "admin", "password": "x", "provisioned_resource_ids": []},
                        ],
                    },
                },
            },
        )

        result = fs._fulfillment_result_to_legacy_shape(envelope)

        assert "authentication" not in result


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
                    connection_info={"vm_name": "vm-1"},
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
            vm_target="tenant-abcd",
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
        assert begin_body.fulfillment_request.payload["vm_target"] == "tenant-abcd"
        assert begin_body.market == "vms"
        assert begin_body.fulfillment_request.payload["ssh_pubkey"] == "ssh-ed25519 AAAA"
        assert "connectivity" not in begin_body.fulfillment_request.payload
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
        assert result["vm_name"] == "vm-1"
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
            "ssh-ed25519 AAAA", vm_host="kvm1", vm_target="tenant-abcd",
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

        from compute_provisioning import ComputeProvisioningJobError

        with pytest.raises(ComputeProvisioningJobError, match="provisioning failed"):
            await fs._do_provision(
                "ssh-ed25519 AAAA", vm_host="kvm1", vm_target="tenant-abcd",
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
async def test_generated_vm_target_survives_context_fulfillment_and_lease_registration(
    monkeypatch,
    tmp_path,
):
    """Exercise target generation across context, fulfillment, and lease seams.

    The storefront project deliberately does not depend on the provider adapter,
    so this test validates the shared wire invariant directly rather than importing
    the adapter's private Pydantic model. Provider-model validation remains covered
    in the provisioning-adapter suite.
    """

    plan = SimpleNamespace(
        order_id="listing-1",
        required_attributes={"vcpu_count": 2},
    )
    monkeypatch.setattr(vfs, "build_vm_fulfillment_plan", lambda **_: plan)

    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "target-survival.db")
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
            "vm_host": "host-1",
            "site": "site-1",
        }),
        commit=AsyncMock(),
    )
    observed: dict[str, str] = {}

    async def validating_provision_vm(
        ssh_public_key: str,
        *,
        vm_target: str,
        on_job_submitted,
        **_: object,
    ) -> dict[str, object]:
        assert isinstance(vm_target, str)
        assert vm_target.startswith("tenant-")
        assert len(vm_target) > len("tenant-")
        assert ssh_public_key
        observed["provision"] = vm_target
        await on_job_submitted("fulfillment-1")
        return {"vm_name": vm_target, "authentication": {}}

    async def register_lease(*, vm_target: str, **_: object) -> None:
        observed["lease"] = vm_target

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
        provision_vm=validating_provision_vm,
        schedule_shutdown=AsyncMock(),
        register_lease=register_lease,
    )
    await asyncio.sleep(0)

    persisted = await sqlite_client.load_escrow(escrow_uid="escrow-1")
    assert persisted is not None
    context = json.loads(persisted["fulfillment_context"])
    payload = context["payload"]["fulfillment_request"]["payload"]
    persisted_vm_target = payload["vm_target"]
    assert isinstance(persisted_vm_target, str)
    assert persisted_vm_target.startswith("tenant-")
    assert payload["ssh_pubkey"] == "ssh-ed25519 test"
    assert capacity.reserve.await_args.args == (lifecycle.capacity_binding,)
    assert observed == {
        "provision": persisted_vm_target,
        "lease": persisted_vm_target,
    }
    assert result["status"] == "fulfilled"


@pytest.mark.asyncio
async def test_post_provision_commit_and_lease_registration_do_not_require_resource_id(
    monkeypatch,
    tmp_path,
):
    """Regression test for the opaque-reservation post-provision gap.

    ``kit/site``'s ``/reservations`` endpoint strips ``resource_id``,
    ``capacity_bucket_id``, and ``backing_resource_id`` from every
    reservation response -- the capacity boundary negotiates on pooled
    capacity, not a pinned physical resource, so ``reserve()`` legitimately
    returns without them. The previous test above exercises a ``reserve()``
    double that (unrealistically) still supplies ``resource_id``/``vm_host``,
    so it cannot catch a regression where the post-provision lease-window
    refresh or lease registration is gated on those fields being present.
    This test uses the real, opaque shape and asserts both calls still fire.
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
        commit=AsyncMock(),
    )

    async def provision_vm(
        ssh_public_key: str, *, vm_target: str, on_job_submitted, **_: object,
    ) -> dict[str, object]:
        await on_job_submitted("fulfillment-1")
        return {"vm_name": vm_target, "authentication": {}}

    register_lease = AsyncMock()

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
        schedule_shutdown=AsyncMock(),
        register_lease=register_lease,
    )
    await asyncio.sleep(0)

    assert result["status"] == "fulfilled"
    assert capacity.reserve.await_args.args == (lifecycle.capacity_binding,)
    # `commit()` is also called earlier, atomically, when there is no
    # pre-existing TTL hold to refresh (`_reserve_capacity_for_obligation` ->
    # `_commit_fresh_reservation`); this test only asserts the *post-provision*
    # lease-window-refresh call this regression targets is not skipped.
    assert capacity.commit.await_count >= 1
    post_provision_commit = capacity.commit.await_args
    assert post_provision_commit.kwargs["capacity_reservation_id"] == "reservation-1"
    assert post_provision_commit.kwargs["resource_id"] is None

    register_lease.assert_awaited_once()
    assert register_lease.await_args.kwargs["capacity_reservation_id"] == "reservation-1"
    assert register_lease.await_args.kwargs["resource_id"] is None
    assert register_lease.await_args.kwargs["vm_host"] is None
