"""
Integration test fixtures.

Starts the full FastAPI application with:
  - A real in-memory SQLite database (fresh per test)
  - A real AsyncJobQueue (fresh per test, with on_job_started seam)
  - AnsibleService overridden with a MagicMock — the only external boundary
  - Auth gate open (storefront_admin_key unset in test settings)

Pattern for exercising the background job loop without sleeps
-------------------------------------------------------------
AsyncJobQueue accepts an ``on_job_started`` callback that fires synchronously
inside the dispatch loop the moment a job_id is dequeued.  Tests inject an
asyncio.Event via this seam and await it instead of sleeping:

    job_dispatched = asyncio.Event()
    # ... fixture injects the event ...
    response = await client.post("/api/v1/hosts/kvm1/vms/", json={...})
    await job_dispatched.wait()   # no sleep — fires exactly once per job
    # Now safe to inspect DB, assert on result, etc.

See Architecture.md — Testing Strategy — Integration Tests for the full
rationale.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

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


# ---------------------------------------------------------------------------
# Async test client for /test/* endpoints (shared across integration tests)
# ---------------------------------------------------------------------------

class AsyncProvisioningTestClientError(Exception):
    """Non-2xx response from the provisioning test controller."""
    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        self.status_code = status
        super().__init__(f"{method} {path} -> {status}: {body[:200]}")


class AsyncProvisioningTestClient:
    """Async typed client for the provisioning service /test/* endpoints.

    Used by integration tests that need to call test-mode control endpoints
    (mock rules, job evaluation). Follows the architecture rule that test
    bodies must not contain raw HTTP calls — all calls go through named methods.
    """

    def __init__(self, transport: ASGITransport) -> None:
        self._client = AsyncClient(transport=transport, base_url="http://test")

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncProvisioningTestClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    async def _get(self, path: str, *, params: dict | None = None, timeout: float = 15.0) -> dict:
        resp = await self._client.get(path, params=params or {}, timeout=timeout)
        if resp.status_code >= 400:
            raise AsyncProvisioningTestClientError("GET", path, resp.status_code, resp.text)
        return resp.json()

    async def _post(self, path: str, body: dict | None = None) -> dict:
        resp = await self._client.post(path, json=body or {})
        if resp.status_code >= 400:
            raise AsyncProvisioningTestClientError("POST", path, resp.status_code, resp.text)
        return resp.json()

    async def _delete(self, path: str) -> dict:
        resp = await self._client.delete(path)
        if resp.status_code >= 400:
            raise AsyncProvisioningTestClientError("DELETE", path, resp.status_code, resp.text)
        return resp.json()

    async def add_mock_rule(
        self,
        *,
        rule_id: str = "",
        match: dict | None = None,
        pause_before_result: bool = False,
        result_stdout: str | None = None,
        fail_with: str | None = None,
    ) -> dict:
        """POST /test/mock-rules"""
        body: dict = {
            "rule_id": rule_id,
            "match": match or {},
            "pause_before_result": pause_before_result,
        }
        if result_stdout is not None:
            body["result_stdout"] = result_stdout
        if fail_with is not None:
            body["fail_with"] = fail_with
        return await self._post("/test/mock-rules", body)

    async def list_mock_rules(self) -> list[dict]:
        """GET /test/mock-rules"""
        return await self._get("/test/mock-rules")  # type: ignore[return-value]

    async def delete_mock_rule(self, rule_id: str) -> dict:
        """DELETE /test/mock-rules/{rule_id}"""
        return await self._delete(f"/test/mock-rules/{rule_id}")

    async def resume_rule(self, rule_id: str) -> dict:
        """POST /test/mock-rules/{rule_id}/resume"""
        return await self._post(f"/test/mock-rules/{rule_id}/resume")

    async def job_summary(self) -> dict:
        """GET /test/jobs/summary"""
        return await self._get("/test/jobs/summary")

    async def wait_for_job(self, job_id: str, *, timeout: float = 30.0) -> dict:
        """GET /test/jobs/{job_id}/wait -- long-poll until terminal."""
        return await self._get(
            f"/test/jobs/{job_id}/wait",
            params={"timeout": timeout},
            timeout=timeout + 5.0,
        )

    async def drain(self, *, timeout: float = 60.0) -> dict:
        """GET /test/jobs/drain"""
        return await self._get(
            "/test/jobs/drain",
            params={"timeout": timeout},
            timeout=timeout + 5.0,
        )

    async def evaluate_job(
        self,
        host: str,
        *,
        vm_target: str = "eval-target",
        ssh_pubkey: str | None = None,
        vm_action: str = "create",
    ) -> dict:
        """POST /test/evaluate-job — dry-run job evaluation."""
        body: dict = {"host": host, "vm_target": vm_target, "vm_action": vm_action}
        if ssh_pubkey is not None:
            body["ssh_pubkey"] = ssh_pubkey
        return await self._post("/test/evaluate-job", body)
from main import app
from services.ansible_service import AnsibleResult, AnsibleRun, AnsibleService
from services.async_job_queue import AsyncJobQueue
from services.host_service import HostService
from services.job_service import AnsibleJobService
from services.mock_ansible_service import ProgrammableMockAnsibleService
from services.system_service import SystemService


# ---------------------------------------------------------------------------
# Representative playbook stdout for a successful vm_create job.
# Contains a vm_creation_data JSON block that AnsibleService.parse_playbook_result
# will extract into the job result.  Credentials are embedded so the credential
# storage path is exercised.
# ---------------------------------------------------------------------------

FAKE_CREATE_STDOUT = """\
PLAY [Provision VM] ***********************************************************

TASK [debug] ******************************************************************
ok: [kvm1] => {
    "vm_creation_data": {
        "action": "create",
        "vm_name": "agent-vm-01",
        "status": "running",
        "host": "kvm1",
        "timestamp": "2025-01-01T00:00:00Z",
        "tenant_user": "agentvm01",
        "external_ssh_port": "54321",
        "vm_ip_internal": "192.168.122.50",
        "authentication": {
            "tenant": {
                "password": "tenantpw",
                "key_type": "generated",
                "ssh_commands": {
                    "internal": "ssh -i key agentvm01@192.168.122.50",
                    "external": "ssh -i key -p 54321 agentvm01@10.0.0.1"
                }
            },
            "root": {
                "password": "rootpw",
                "ssh_commands": {"internal": "ssh root@192.168.122.50"},
                "ssh_key_path_host": "/root/.ssh/agent-vm-01_root_ed25519"
            }
        }
    }
}
"""


# ---------------------------------------------------------------------------
# Database fixture — fresh in-memory SQLite per test
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


# ---------------------------------------------------------------------------
# Fake inventory path — points at the real test inventory fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_inventory_path(tmp_path) -> Path:
    """Write a minimal Ansible INI inventory to a temp file."""
    hosts = tmp_path / "hosts"
    hosts.write_text(
        "[kvm_hosts]\n"
        "kvm1  ansible_host=10.0.0.1  ansible_user=root  "
        "ansible_ssh_private_key_file=~/.ssh/id_ed25519\n"
    )
    return hosts


# ---------------------------------------------------------------------------
# Mock AnsibleService — synchronous happy-path by default
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_ansible(fake_inventory_path) -> MagicMock:
    """AnsibleService mock with a successful create playbook response."""
    mock = MagicMock(spec=AnsibleService)

    fake_run = AnsibleRun(
        process=MagicMock(),
        process_id=99999,
        vars_path=Path("/tmp/fake_vars.yml"),
    )
    fake_result = AnsibleResult(
        stdout=FAKE_CREATE_STDOUT,
        stderr="",
        process_id=99999,
    )

    mock.build_vars_file.return_value = Path("/tmp/fake_vars.yml")
    mock.start_playbook.return_value = fake_run
    mock.wait_for_playbook = AsyncMock(return_value=fake_result)
    mock.lookup_host_ip.return_value = "10.0.0.1"

    # parse_playbook_result uses real logic — delegate to a real instance
    # configured with a mock settings so lookup_host_ip works correctly.
    real_settings = MagicMock()
    real_settings.resolved_inventory_path = fake_inventory_path
    real_ansible_impl = AnsibleService(real_settings)
    mock.parse_playbook_result.side_effect = real_ansible_impl.parse_playbook_result

    # write_inventory — return a temp path (content irrelevant; Ansible never runs)
    import tempfile
    fake_inv_tmp = Path(tempfile.gettempdir()) / "test_inventory.ini"
    fake_inv_tmp.write_text("[kvm_hosts]\nkvm1  ansible_host=10.0.0.1  ansible_user=root\n")
    mock.write_inventory.return_value = fake_inv_tmp

    # check_connectivity_with_inventory — synchronous mock returning reachable
    from models.ansible import ConnectivityResult
    from unittest.mock import AsyncMock as _AsyncMock
    mock.check_connectivity_with_inventory = _AsyncMock(
        return_value=ConnectivityResult(host="kvm1", reachable=True, detail="mock ping ok")
    )

    return mock


# ---------------------------------------------------------------------------
# App fixture — wires all overrides and starts the job processing loop
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client_and_queue(
    session_factory, fake_ansible
) -> AsyncIterator[tuple[AsyncClient, AsyncJobQueue]]:
    """Yield (httpx.AsyncClient, AsyncJobQueue) with overrides applied.

    The job queue is fresh per-test.  Use the ``on_job_started`` seam to
    synchronise tests against the background loop without any sleeps.

    Container providers are overridden for the duration of the test and
    reset afterwards so tests are fully isolated.
    """
    # Build services directly — bypass the container's DB singleton so we use
    # the fresh per-test in-memory DB.
    mock_settings = MagicMock(
        default_vm_host="kvm1",
        default_max_retries=3,
        retry_backoff_initial_seconds=60,
        retry_backoff_multiplier=2.0,
        retry_backoff_max_seconds=3600,
        ansible_timeout_seconds=30,
        non_retryable_errors=["UNREACHABLE", "Domain not found"],
        frp_server_addr="",
        frp_domain="",
        frp_dashboard_password="",
        resolved_playbook_path=Path("/fake/playbook.yml"),
        resolved_inventory_path=Path("/fake/hosts"),
        ssh_decryption_key="",
        database_url="sqlite:///:memory:",
        lease_watchdog_grace_period_seconds=300,
        lease_watchdog_enabled=False,  # Don't start background timer in tests
        storefront_url="http://test-storefront:8001",
        storefront_admin_key="test-admin-key",
    )

    host_service = HostService(
        session_factory=session_factory,
        settings=mock_settings,
    )

    job_service = AnsibleJobService(
        settings=mock_settings,
        session_factory=session_factory,
        ansible_service=fake_ansible,
        host_service=host_service,
    )

    system_service = SystemService(
        ansible_service=fake_ansible,
        settings=mock_settings,
        host_service=host_service,
    )

    from services.lease_service import LeaseService
    from services.lease_lifecycle_service import LeaseLifecycleService
    lease_service = LeaseService(session_factory=session_factory)
    lease_lifecycle_service = LeaseLifecycleService(
        lease_service=lease_service,
        settings=mock_settings,
        job_service=None,  # tests use direct-patch path; no real Ansible jobs
    )

    from services.capacity_ledger import CapacityLedgerService
    capacity_ledger_service = CapacityLedgerService(session_factory=session_factory)

    # Override container providers
    app.container.ansible_service.override(fake_ansible)
    app.container.job_service.override(job_service)
    app.container.system_service.override(system_service)
    app.container.session_factory.override(session_factory)
    app.container.host_service.override(host_service)
    app.container.lease_service.override(lease_service)
    app.container.lease_lifecycle_service.override(lease_lifecycle_service)
    app.container.capacity_ledger_service.override(capacity_ledger_service)

    # Wire resolved module-level variables
    _container_module.resolved_job_service = job_service
    _container_module.resolved_session_factory = session_factory
    _container_module.resolved_ansible_service = fake_ansible
    _container_module.resolved_system_service = system_service
    _container_module.resolved_host_service = host_service
    _container_module.resolved_lease_service = lease_service
    _container_module.resolved_lease_lifecycle_service = lease_lifecycle_service
    _container_module.resolved_capacity_ledger_service = capacity_ledger_service

    # Fresh queue per test — caller can inject on_job_started via fixture params
    job_queue = AsyncJobQueue(max_concurrent=2)
    _container_module.resolved_job_queue = job_queue

    processing_task = asyncio.create_task(
        job_queue.start(job_service._process_job),
        name="test-job-processing-loop",
    )

    transport = ASGITransport(app=app)

    # Mount the test controller if not already present
    from controllers.test_controller import make_router as _make_test_router
    _test_prefix = "/test"
    _already_mounted = any(
        getattr(r, "path", "").startswith(_test_prefix) for r in app.routes
    )
    if not _already_mounted:
        app.include_router(_make_test_router())

    async with AsyncClient(transport=transport, base_url="http://test") as http:
        client = ProvisioningClient(
            "http://test",
            transport=transport,
        )
        yield client, job_queue

    processing_task.cancel()
    try:
        await processing_task
    except asyncio.CancelledError:
        pass

    # Reset container overrides
    app.container.ansible_service.reset_override()
    app.container.job_service.reset_override()
    app.container.system_service.reset_override()
    app.container.session_factory.reset_override()
    app.container.host_service.reset_override()
    app.container.lease_service.reset_override()
    app.container.lease_lifecycle_service.reset_override()
    app.container.capacity_ledger_service.reset_override()


@pytest_asyncio.fixture
async def test_client(client_and_queue) -> AsyncIterator[AsyncProvisioningTestClient]:
    """Yield an AsyncProvisioningTestClient connected to the in-process app.

    Depends on client_and_queue to ensure the full service stack (including
    the test controller router) is mounted and the container is wired.
    """
    job_service = _container_module.resolved_job_service
    mock_settings = getattr(job_service, "_settings", MagicMock())
    programmable_mock = ProgrammableMockAnsibleService(mock_settings)

    original_ansible = _container_module.resolved_ansible_service
    _container_module.resolved_ansible_service = programmable_mock
    try:
        transport = ASGITransport(app=app)
        async with AsyncProvisioningTestClient(transport) as tc:
            yield tc
    finally:
        _container_module.resolved_ansible_service = original_ansible
