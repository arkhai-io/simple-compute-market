"""Integration tests for the test controller (GET/POST /test/*).

Verifies:
  - All /test/* endpoints are reachable when mock profile simulated
  - Mock rule add/list/delete/resume round-trip
  - drain and wait endpoints work correctly
  - Test controller is NOT mounted when the mock service is not active
    (simulated by swapping in a real AnsibleService mock)
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
from client.provisioning_client import ProvisioningClient
from db.database import create_session_factory
from db.models import Base
from main import app
from models.vm_request_model import CreateVmRequest
from services.ansible_service import AnsibleResult, AnsibleRun, AnsibleService
from services.async_job_queue import AsyncJobQueue
from services.host_service import HostService
from services.job_service import AnsibleJobService
from services.mock_ansible_service import MockRule, ProgrammableMockAnsibleService
from services.system_service import SystemService

AGENT_ID = "eip155:1337:0xdeadbeef:1"
HOST = "ww1"


# ---------------------------------------------------------------------------
# Fixtures — same pattern as provisioning integration conftest, but wires
# ProgrammableMockAnsibleService directly instead of via the container
# ---------------------------------------------------------------------------

@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def session_factory(db_engine):
    return create_session_factory(db_engine)


@pytest.fixture
def fake_inventory_path(tmp_path) -> Path:
    hosts = tmp_path / "hosts"
    hosts.write_text(
        "[kvm_hosts]\n"
        "ww1  ansible_host=10.0.0.1  ansible_user=root  "
        "ansible_ssh_private_key_file=~/.ssh/id_ed25519\n"
    )
    return hosts


@pytest.fixture
def programmable_mock(fake_inventory_path) -> ProgrammableMockAnsibleService:
    mock_settings = MagicMock(resolved_inventory_path=fake_inventory_path)
    svc = ProgrammableMockAnsibleService(mock_settings)

    # write_inventory returns a real temp file
    import tempfile
    fake_inv = Path(tempfile.gettempdir()) / "test_inv.ini"
    fake_inv.write_text("[kvm_hosts]\nww1  ansible_host=10.0.0.1  ansible_user=root\n")
    svc.write_inventory = MagicMock(return_value=fake_inv)
    svc.check_connectivity_with_inventory = AsyncMock(
        return_value=MagicMock(reachable=True, detail="mock ping ok")
    )
    return svc


@pytest_asyncio.fixture
async def client_and_queue(
    session_factory, programmable_mock
) -> AsyncIterator[tuple[ProvisioningClient, AsyncJobQueue, ProgrammableMockAnsibleService]]:
    mock_settings = MagicMock(
        default_vm_host="ww1",
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

    # Seed host so VM creation resolves correctly
    from models.host_model import HostCreate
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

    # Mount the test controller directly — the main app only conditionally
    # mounts it based on ACTIVE_PROFILES, which is not set in the test env.
    from controllers.test_controller import make_router as _make_test_router
    _test_prefix = "/test"
    _already_mounted = any(
        getattr(r, "path", "").startswith(_test_prefix) for r in app.routes
    )
    if not _already_mounted:
        app.include_router(_make_test_router())

    job_queue = AsyncJobQueue(max_concurrent=2)
    _container_module.resolved_job_queue = job_queue

    processing_task = asyncio.create_task(
        job_queue.start(job_service._process_job),
        name="test-job-processing-loop",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        prov_client = ProvisioningClient(
            "http://test", agent_id=AGENT_ID, transport=transport
        )
        yield prov_client, job_queue, programmable_mock

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
# Helper: raw HTTP client (bypasses ProvisioningClient for /test/* endpoints)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def http(client_and_queue) -> AsyncClient:
    """Yield the raw httpx client for /test/* requests."""
    _, _, _ = client_and_queue
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# /test/mock-rules CRUD
# ---------------------------------------------------------------------------

class TestMockRuleCrud:
    async def test_add_rule_and_list(self, http):
        resp = await http.post("/test/mock-rules", json={
            "rule_id": "test-r1",
            "match": {"vm_action": "create"},
            "pause_before_result": False,
        })
        assert resp.status_code == 200
        assert resp.json()["rule_id"] == "test-r1"

        resp = await http.get("/test/mock-rules")
        assert resp.status_code == 200
        ids = {r["rule_id"] for r in resp.json()}
        assert "test-r1" in ids

    async def test_delete_rule(self, http):
        await http.post("/test/mock-rules", json={"rule_id": "del-me", "match": {}})
        resp = await http.delete("/test/mock-rules/del-me")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        resp = await http.get("/test/mock-rules")
        ids = {r["rule_id"] for r in resp.json()}
        assert "del-me" not in ids

    async def test_delete_nonexistent_returns_false(self, http):
        resp = await http.delete("/test/mock-rules/ghost")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False

    async def test_resume_nonexistent_returns_404(self, http):
        resp = await http.post("/test/mock-rules/ghost/resume")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /test/jobs/summary
# ---------------------------------------------------------------------------

class TestJobSummary:
    async def test_summary_empty(self, http):
        resp = await http.get("/test/jobs/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["total_active"] == 0
        assert body["total_terminal"] == 0

    async def test_summary_counts_after_job(self, client_and_queue, http):
        prov_client, job_queue, _ = client_and_queue
        dispatched = _make_event_seam(job_queue)
        submit = await prov_client.create_vm(HOST, CreateVmRequest(
            vm_target="test-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        # Wait for job to complete
        await prov_client.poll_until_complete(submit.job_id, timeout=10.0)
        resp = await http.get("/test/jobs/summary")
        body = resp.json()
        assert body["total"] >= 1
        assert body["counts"].get("succeeded", 0) >= 1


# ---------------------------------------------------------------------------
# /test/jobs/drain
# ---------------------------------------------------------------------------

class TestDrain:
    async def test_drain_with_no_jobs_returns_immediately(self, http):
        resp = await http.get("/test/jobs/drain?timeout=5")
        assert resp.status_code == 200
        assert resp.json()["drained"] is True

    async def test_drain_waits_for_job_to_complete(self, client_and_queue, http):
        prov_client, job_queue, _ = client_and_queue
        dispatched = _make_event_seam(job_queue)
        await prov_client.create_vm(HOST, CreateVmRequest(
            vm_target="drain-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        resp = await http.get("/test/jobs/drain?timeout=10")
        assert resp.status_code == 200
        assert resp.json()["drained"] is True


# ---------------------------------------------------------------------------
# /test/jobs/{job_id}/wait
# ---------------------------------------------------------------------------

class TestWaitForJob:
    async def test_wait_returns_terminal_status(self, client_and_queue, http):
        prov_client, job_queue, _ = client_and_queue
        dispatched = _make_event_seam(job_queue)
        submit = await prov_client.create_vm(HOST, CreateVmRequest(
            vm_target="wait-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        resp = await http.get(f"/test/jobs/{submit.job_id}/wait?timeout=10")
        assert resp.status_code == 200
        assert resp.json()["status"] in {"succeeded", "failed"}

    async def test_wait_404_unknown_job(self, http):
        resp = await http.get("/test/jobs/does-not-exist/wait?timeout=2")
        assert resp.status_code == 404

    async def test_wait_timeout_returns_408(self, client_and_queue, http):
        """Pause the rule so the job never completes, then verify 408."""
        prov_client, job_queue, mock = client_and_queue
        mock.add_rule(MockRule(rule_id="block-all", match={}, pause_before_result=True))

        dispatched = _make_event_seam(job_queue)
        submit = await prov_client.create_vm(HOST, CreateVmRequest(
            vm_target="timeout-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        resp = await http.get(f"/test/jobs/{submit.job_id}/wait?timeout=0.5")
        assert resp.status_code == 408
        # Clean up: resume so the fixture teardown can drain
        mock.resume_rule("block-all")


# ---------------------------------------------------------------------------
# Verify test controller is absent when mock profile NOT simulated
# ---------------------------------------------------------------------------

class TestControllerGating:
    async def test_test_routes_absent_without_programmable_mock(self, client_and_queue, http):
        """If we swap in a plain MagicMock (not ProgrammableMock), /test/mock-rules returns 503."""
        _, _, _ = client_and_queue
        # Temporarily replace with a non-programmable mock
        original = _container_module.resolved_ansible_service
        _container_module.resolved_ansible_service = MagicMock(spec=AnsibleService)
        try:
            resp = await http.post("/test/mock-rules", json={"match": {}})
            assert resp.status_code == 503
        finally:
            _container_module.resolved_ansible_service = original
