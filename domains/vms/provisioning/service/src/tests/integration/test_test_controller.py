"""Integration tests for the test controller (GET/POST /test/*).

Verifies:
  - All /test/* endpoints are reachable when mock profile is simulated
  - Mock rule add/list/delete/resume round-trip
  - drain and wait endpoints work correctly
  - Test controller is NOT mounted when the mock service is not active
    (simulated by swapping in a real AnsibleService mock)

All calls go through AsyncProvisioningTestClient — no raw HTTP calls in
test bodies.  See AsyncProvisioningTestClient below for rationale.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import container as _container_module
from provisioning_client import ProvisioningClient, ProvisioningError
from db.database import create_session_factory
from db.models import Base
from main import app
from provisioning_client.models import CreateVmRequest
from services.ansible_service import AnsibleService
from services.async_job_queue import AsyncJobQueue
from services.host_service import HostService
from services.job_service import AnsibleJobService
from services.mock_ansible_service import MockRule, ProgrammableMockAnsibleService
from services.system_service import SystemService

HOST = "kvm1"


# ---------------------------------------------------------------------------
# AsyncProvisioningTestClient
#
# The canonical ProvisioningTestClient (e2e-tests/src/) is sync-only.
# This async variant is backed by the same ASGITransport as the main
# ProvisioningClient so all calls share the in-process app.  No raw HTTP
# calls appear in test bodies — all test code calls named methods here.
# ---------------------------------------------------------------------------

from tests.integration.conftest import AsyncProvisioningTestClient, AsyncProvisioningTestClientError
@pytest.fixture
def programmable_mock(fake_inventory_path) -> ProgrammableMockAnsibleService:
    mock_settings = MagicMock(resolved_inventory_path=fake_inventory_path)
    svc = ProgrammableMockAnsibleService(mock_settings)
    import tempfile
    fake_inv = Path(tempfile.gettempdir()) / "test_inv.ini"
    fake_inv.write_text("[kvm_hosts]\nkvm1  ansible_host=10.0.0.1  ansible_user=root\n")
    svc.write_inventory = MagicMock(return_value=fake_inv)
    svc.check_connectivity_with_inventory = AsyncMock(
        return_value=MagicMock(reachable=True, detail="mock ping ok")
    )
    return svc


@pytest_asyncio.fixture
async def client_and_queue(
    session_factory, programmable_mock
) -> AsyncIterator[tuple[ProvisioningClient, AsyncJobQueue, ProgrammableMockAnsibleService, AsyncProvisioningTestClient]]:
    mock_settings = MagicMock(
        default_vm_host="kvm1",
        default_max_retries=3,
        retry_backoff_initial_seconds=60,
        retry_backoff_multiplier=2.0,
        retry_backoff_max_seconds=3600,
        ansible_timeout_seconds=30,
        non_retryable_errors=["UNREACHABLE"],
        frp_server_addr="",
        frp_domain="",
        frp_dashboard_password="",
        resolved_playbook_path=Path("/fake/playbook.yml"),
        resolved_inventory_path=Path("/fake/hosts"),
        ssh_decryption_key="",
        database_url="sqlite:///:memory:",
    )

    host_service = HostService(session_factory=session_factory, settings=mock_settings)
    from provisioning_client.models import HostCreate
    host_service.register_host(HostCreate(
        name=HOST,
        kvm_host="10.0.0.1",
        ssh_user="root",
        ssh_key_type="path",
        ssh_key_value="~/.ssh/id_ed25519",
        gpu_count=0,
    ))

    job_service = AnsibleJobService(
        settings=mock_settings,
        session_factory=session_factory,
        ansible_service=programmable_mock,
        host_service=host_service,
    )
    system_service = SystemService(
        ansible_service=programmable_mock,
        settings=mock_settings,
        host_service=host_service,
    )

    app.container.ansible_service.override(programmable_mock)
    app.container.job_service.override(job_service)
    app.container.system_service.override(system_service)
    app.container.session_factory.override(session_factory)
    app.container.host_service.override(host_service)

    _container_module.resolved_job_service = job_service
    _container_module.resolved_session_factory = session_factory
    _container_module.resolved_ansible_service = programmable_mock
    _container_module.resolved_system_service = system_service
    _container_module.resolved_host_service = host_service

    from controllers.test_controller import make_router as _make_test_router
    _test_prefix = "/test"
    _already_mounted = any(
        getattr(r, "path", "").startswith(_test_prefix) for r in app.routes
    )
    if not _already_mounted:
        app.include_router(_make_test_router())

    job_queue = AsyncJobQueue(max_concurrent=2)
    _container_module.resolved_job_queue = job_queue
    _container_module.resolved_vm_operations_service = app.container.vm_operations_service()
    _container_module.resolved_host_operations_service = app.container.host_operations_service()

    processing_task = asyncio.create_task(
        job_queue.start(job_service._process_job),
        name="test-job-processing-loop",
    )

    transport = ASGITransport(app=app)
    prov_client = ProvisioningClient("http://test", transport=transport)
    test_client = AsyncProvisioningTestClient(transport)

    yield prov_client, job_queue, programmable_mock, test_client

    await test_client.close()
    processing_task.cancel()
    try:
        await processing_task
    except asyncio.CancelledError:
        pass

    app.container.ansible_service.reset_override()
    app.container.job_service.reset_override()
    app.container.system_service.reset_override()
    app.container.session_factory.reset_override()
    app.container.host_service.reset_override()
    _container_module.resolved_vm_operations_service = None
    _container_module.resolved_host_operations_service = None


def _make_event_seam(job_queue: AsyncJobQueue) -> asyncio.Event:
    dispatched = asyncio.Event()
    original = job_queue._on_job_started

    def _cb(job_id: str) -> None:
        dispatched.set()
        if original:
            original(job_id)

    job_queue._on_job_started = _cb
    return dispatched


# ---------------------------------------------------------------------------
# /test/mock-rules CRUD
# ---------------------------------------------------------------------------

class TestMockRuleCrud:
    async def test_add_rule_and_list(self, client_and_queue):
        _, _, _, test_client = client_and_queue
        result = await test_client.add_mock_rule(
            rule_id="test-r1",
            match={"vm_action": "create"},
            pause_before_result=False,
        )
        assert result["rule_id"] == "test-r1"

        rules = await test_client.list_mock_rules()
        ids = {r["rule_id"] for r in rules}
        assert "test-r1" in ids

    async def test_delete_rule(self, client_and_queue):
        _, _, _, test_client = client_and_queue
        await test_client.add_mock_rule(rule_id="del-me", match={})
        result = await test_client.delete_mock_rule("del-me")
        assert result["deleted"] is True

        rules = await test_client.list_mock_rules()
        ids = {r["rule_id"] for r in rules}
        assert "del-me" not in ids

    async def test_delete_nonexistent_returns_false(self, client_and_queue):
        _, _, _, test_client = client_and_queue
        result = await test_client.delete_mock_rule("ghost")
        assert result["deleted"] is False

    async def test_resume_nonexistent_returns_404(self, client_and_queue):
        _, _, _, test_client = client_and_queue
        with pytest.raises(AsyncProvisioningTestClientError) as exc_info:
            await test_client.resume_rule("ghost")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# /test/jobs/summary
# ---------------------------------------------------------------------------

class TestJobSummary:
    async def test_summary_empty(self, client_and_queue):
        _, _, _, test_client = client_and_queue
        body = await test_client.job_summary()
        assert body["total"] == 0
        assert body["total_active"] == 0
        assert body["total_terminal"] == 0

    async def test_summary_counts_after_job(self, client_and_queue):
        prov_client, job_queue, _, test_client = client_and_queue
        dispatched = _make_event_seam(job_queue)
        submit = await prov_client.create_vm(HOST, CreateVmRequest(
            vm_target="test-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        await prov_client.poll_until_complete(submit.job_id, timeout=10.0)
        body = await test_client.job_summary()
        assert body["total"] >= 1
        assert body["counts"].get("succeeded", 0) >= 1


# ---------------------------------------------------------------------------
# /test/jobs/drain
# ---------------------------------------------------------------------------

class TestDrain:
    async def test_drain_with_no_jobs_returns_immediately(self, client_and_queue):
        _, _, _, test_client = client_and_queue
        result = await test_client.drain(timeout=5.0)
        assert result["drained"] is True

    async def test_drain_waits_for_job_to_complete(self, client_and_queue):
        prov_client, job_queue, _, test_client = client_and_queue
        dispatched = _make_event_seam(job_queue)
        await prov_client.create_vm(HOST, CreateVmRequest(
            vm_target="drain-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        result = await test_client.drain(timeout=10.0)
        assert result["drained"] is True


# ---------------------------------------------------------------------------
# /test/jobs/{job_id}/wait
# ---------------------------------------------------------------------------

class TestWaitForJob:
    async def test_wait_returns_terminal_status(self, client_and_queue):
        prov_client, job_queue, _, test_client = client_and_queue
        dispatched = _make_event_seam(job_queue)
        submit = await prov_client.create_vm(HOST, CreateVmRequest(
            vm_target="wait-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        result = await test_client.wait_for_job(submit.job_id, timeout=10.0)
        assert result["status"] in {"succeeded", "failed"}

    async def test_wait_404_unknown_job(self, client_and_queue):
        _, _, _, test_client = client_and_queue
        with pytest.raises(AsyncProvisioningTestClientError) as exc_info:
            await test_client.wait_for_job("does-not-exist", timeout=2.0)
        assert exc_info.value.status_code == 404

    async def test_wait_timeout_returns_408(self, client_and_queue):
        prov_client, job_queue, mock, test_client = client_and_queue
        mock.add_rule(MockRule(rule_id="block-all", match={}, pause_before_result=True))
        dispatched = _make_event_seam(job_queue)
        submit = await prov_client.create_vm(HOST, CreateVmRequest(
            vm_target="timeout-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        with pytest.raises(AsyncProvisioningTestClientError) as exc_info:
            await test_client.wait_for_job(submit.job_id, timeout=0.5)
        assert exc_info.value.status_code == 408
        mock.resume_rule("block-all")


# ---------------------------------------------------------------------------
# Verify test controller gating
# ---------------------------------------------------------------------------

class TestControllerGating:
    async def test_test_routes_absent_without_programmable_mock(self, client_and_queue):
        # Rejection-path test: swapping in a non-programmable mock causes
        # /test/mock-rules to return 503. Asserts on status code only.
        _, _, _, test_client = client_and_queue
        original = _container_module.resolved_ansible_service
        _container_module.resolved_ansible_service = MagicMock(spec=AnsibleService)
        try:
            with pytest.raises(AsyncProvisioningTestClientError) as exc_info:
                await test_client.add_mock_rule(match={})
            assert exc_info.value.status_code == 503
        finally:
            _container_module.resolved_ansible_service = original
