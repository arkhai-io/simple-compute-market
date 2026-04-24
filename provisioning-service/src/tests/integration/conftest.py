"""
Integration test fixtures.

Starts the full FastAPI application with:
  - A real in-memory SQLite database (fresh per test)
  - A real AsyncJobQueue (fresh per test, with on_job_started seam)
  - AnsibleService overridden with a MagicMock — the only external boundary
  - Auth disabled (PROVISIONING_ENABLE_AUTH=false)

Pattern for exercising the background job loop without sleeps
-------------------------------------------------------------
AsyncJobQueue accepts an ``on_job_started`` callback that fires synchronously
inside the dispatch loop the moment a job_id is dequeued.  Tests inject an
asyncio.Event via this seam and await it instead of sleeping:

    job_dispatched = asyncio.Event()
    # ... fixture injects the event ...
    response = await client.post("/api/v1/hosts/ww1/vms/", json={...})
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
from db.database import create_session_factory
from db.models import Base
from main import app
from services.ansible_service import AnsibleResult, AnsibleRun, AnsibleService
from services.async_job_queue import AsyncJobQueue
from services.host_service import HostService
from services.job_service import AnsibleJobService
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
ok: [ww1] => {
    "vm_creation_data": {
        "action": "create",
        "vm_name": "agent-vm-01",
        "status": "running",
        "host": "ww1",
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
        "ww1  ansible_host=10.0.0.1  ansible_user=root  "
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
    fake_inv_tmp.write_text("[kvm_hosts]\nww1  ansible_host=10.0.0.1  ansible_user=root\n")
    mock.write_inventory.return_value = fake_inv_tmp

    # check_connectivity_with_inventory — synchronous mock returning reachable
    from models.ansible import ConnectivityResult
    from unittest.mock import AsyncMock as _AsyncMock
    mock.check_connectivity_with_inventory = _AsyncMock(
        return_value=ConnectivityResult(host="ww1", reachable=True, detail="mock ping ok")
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
        default_vm_host="ww1",
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

    # Override container providers
    app.container.ansible_service.override(fake_ansible)
    app.container.job_service.override(job_service)
    app.container.system_service.override(system_service)
    app.container.session_factory.override(session_factory)
    app.container.host_service.override(host_service)

    # Wire resolved module-level variables
    _container_module.resolved_job_service = job_service
    _container_module.resolved_session_factory = session_factory
    _container_module.resolved_ansible_service = fake_ansible
    _container_module.resolved_system_service = system_service
    _container_module.resolved_host_service = host_service

    # Fresh queue per test — caller can inject on_job_started via fixture params
    job_queue = AsyncJobQueue(max_concurrent=2)
    _container_module.resolved_job_queue = job_queue

    processing_task = asyncio.create_task(
        job_queue.start(job_service._process_job),
        name="test-job-processing-loop",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, job_queue

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
