"""Unit tests for the storefront-side fulfillment cutover helpers.

Covers ``_fulfillment_result_to_legacy_shape``, ``_poll_fulfillment_until_terminal``,
and ``_connectivity_settings_from_storefront_config`` -- the pure/mockable
pieces of ``_do_provision``'s replacement of the legacy direct-executor-dispatch
path with ``schedule_resource`` -> ``begin_fulfillment`` -> poll status/result.
``_do_provision`` itself is exercised indirectly through these; a full
end-to-end test needs the real settlement/negotiation fixtures
``test_fulfillment_service.py`` already sets up.
"""

from __future__ import annotations

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


class TestConnectivitySettingsFromStorefrontConfig:
    def test_returns_none_when_nothing_configured(self, monkeypatch):
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(frp_server_addr="", frp_domain="", frp_dashboard_password=""),
            raising=False,
        )
        assert fs._connectivity_settings_from_storefront_config() is None

    def test_returns_configured_values(self, monkeypatch):
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(
                frp_server_addr="relay.example.com:7000",
                frp_domain="buyer-vm.example.com",
                frp_dashboard_password="s3cr3t",
            ),
            raising=False,
        )
        result = fs._connectivity_settings_from_storefront_config()
        assert result == {
            "frp_server_addr": "relay.example.com:7000",
            "frp_domain": "buyer-vm.example.com",
            "frp_dashboard_password": "s3cr3t",
        }

    def test_partial_configuration_still_returns_a_dict(self, monkeypatch):
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(frp_server_addr="relay.example.com:7000", frp_domain="", frp_dashboard_password=""),
            raising=False,
        )
        result = fs._connectivity_settings_from_storefront_config()
        assert result == {
            "frp_server_addr": "relay.example.com:7000",
            "frp_domain": None,
            "frp_dashboard_password": None,
        }


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
                return_value=VersionedEnvelope(
                    kind="fulfillment.result.v1",
                    schema_version=1,
                    payload={
                        "provisioned_resources": [{"provisioned_resource_id": "res-1", "status": "active"}],
                        "domain_result": {
                            "kind": "vm.fulfillment.result.v1",
                            "schema_version": 1,
                            "payload": {
                                "connection_info": {"vm_name": "vm-1"},
                                "credentials": [],
                            },
                        },
                    },
                )
            ),
        )
        return client

    async def test_schedules_begins_polls_and_returns_result(
        self, monkeypatch, fulfillment_client,
    ):
        sqlite_client = SimpleNamespace(update_escrow=AsyncMock())
        monkeypatch.setattr(fs, "build_fulfillment_client", lambda *_: fulfillment_client)
        monkeypatch.setattr(fs, "build_capacity_client", lambda *_: SimpleNamespace())
        monkeypatch.setattr(fs, "get_sqlite_client", lambda: sqlite_client)
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(
                timeout=5.0, poll_interval=0.001,
                frp_server_addr="", frp_domain="", frp_dashboard_password="",
            ),
            raising=False,
        )
        job_ids: list[str] = []

        async def _on_job_submitted(job_id: str) -> None:
            job_ids.append(job_id)

        result = await fs._do_provision(
            "ssh-ed25519 AAAA",
            vm_host="kvm1",
            vm_target="tenant-abcd",
            on_job_submitted=_on_job_submitted,
            capacity_reservation_id="res-1",
            deal_ref={"escrow_uid": "escrow-1"},
        )

        fulfillment_client.schedule_resource.assert_awaited_once()
        schedule_request = fulfillment_client.schedule_resource.await_args.args[0]
        assert schedule_request.capacity_reservation_id == "res-1"
        assert schedule_request.market == "vms"

        # Restart-safety persistence: capacity_reservation_id and
        # settlement_resource_id written as soon as scheduling confirms them.
        sqlite_client.update_escrow.assert_any_await(
            escrow_uid="escrow-1",
            capacity_reservation_id="res-1",
            settlement_resource_id="kvm1",
        )

        fulfillment_client.begin_fulfillment.assert_awaited_once()
        begin_body = fulfillment_client.begin_fulfillment.await_args.args[0]
        assert begin_body.capacity_reservation_id == "res-1"
        assert begin_body.fulfillment_request.payload["vm_target"] == "tenant-abcd"
        assert begin_body.fulfillment_request.payload["ssh_pubkey"] == "ssh-ed25519 AAAA"
        assert "connectivity" not in begin_body.fulfillment_request.payload

        assert job_ids == ["fulfillment-1"]
        assert result["vm_name"] == "vm-1"
        assert result["provisioned_resource_ids"] == ["res-1"]

    async def test_includes_connectivity_when_frp_configured(
        self, monkeypatch, fulfillment_client,
    ):
        monkeypatch.setattr(fs, "build_fulfillment_client", lambda *_: fulfillment_client)
        monkeypatch.setattr(fs, "build_capacity_client", lambda *_: SimpleNamespace())
        monkeypatch.setattr(fs, "get_sqlite_client", lambda: SimpleNamespace(update_escrow=AsyncMock()))
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(
                timeout=5.0, poll_interval=0.001,
                frp_server_addr="relay.example.com:7000", frp_domain="", frp_dashboard_password="",
            ),
            raising=False,
        )

        await fs._do_provision(
            "ssh-ed25519 AAAA", vm_host="kvm1", vm_target="tenant-abcd",
            capacity_reservation_id="res-1", deal_ref={},
        )

        begin_body = fulfillment_client.begin_fulfillment.await_args.args[0]
        assert begin_body.fulfillment_request.payload["connectivity"] == {
            "frp_server_addr": "relay.example.com:7000",
            "frp_domain": None,
            "frp_dashboard_password": None,
        }

    async def test_failed_state_raises(self, monkeypatch, fulfillment_client):
        fulfillment_client.get_fulfillment_status = AsyncMock(
            return_value=SimpleNamespace(state="failed", failure_message="provisioning failed")
        )
        monkeypatch.setattr(fs, "build_fulfillment_client", lambda *_: fulfillment_client)
        monkeypatch.setattr(fs, "build_capacity_client", lambda *_: SimpleNamespace())
        monkeypatch.setattr(fs, "get_sqlite_client", lambda: SimpleNamespace(update_escrow=AsyncMock()))
        monkeypatch.setattr(
            fs.settings, "provisioning",
            SimpleNamespace(
                timeout=5.0, poll_interval=0.001,
                frp_server_addr="", frp_domain="", frp_dashboard_password="",
            ),
            raising=False,
        )

        from compute_provisioning import ComputeProvisioningJobError

        with pytest.raises(ComputeProvisioningJobError, match="provisioning failed"):
            await fs._do_provision(
                "ssh-ed25519 AAAA", vm_host="kvm1", vm_target="tenant-abcd",
                capacity_reservation_id="res-1", deal_ref={},
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
        )
        assert status.state == "active"
        client.get_fulfillment_status.assert_awaited_once_with(
            "fulfillment-1", capacity_reservation_id="res-1",
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
