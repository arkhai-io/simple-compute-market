"""Integration tests for the test controller (GET/POST /test/*).

Verifies:
  - All /test/* endpoints are reachable when mock profile is simulated
  - Mock rule add/list/delete/resume round-trip
  - drain and wait endpoints work correctly
  - Test controller is NOT mounted when the mock service is not active
    (simulated by swapping in a runner mock)

All calls go through AsyncProvisioningTestClient — no raw HTTP calls in
test bodies.  See AsyncProvisioningTestClient below for rationale.
"""

from __future__ import annotations
from compute_provisioning_ansible import ssh_connection

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from typing import AsyncIterator

import pytest
from compute_provisioning_ansible.runner import MaterializedInventory
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from market_site import CapacityLedgerService

from compute_provisioning_service.services.capacity_derivation import (
    LegacyHostCapacityDerivation,
)

from .conftest import (
    ProvisioningClients,
    provisioning_clients,
    ADMIN_SIGNER,
    SERVICE_AUTHORITIES,
    SERVICE_SIGNER,
    STOREFRONT_SIGNER,
    _initialize_test_database,
    _install_signed_asgi_transport,
)
from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning_service.middleware.auth import (
    SqlAlchemyProvisioningReplayStore,
)
from compute_provisioning_service.services.principal_authority import (
    SqlAlchemyProvisioningPrincipalAuthority,
)

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.db.database import create_db_engine
from compute_provisioning_service.main import app
from vm_provisioning_operator.models import CreateVmRequest
from compute_provisioning_ansible.runner import AnsibleRunner
from vm_provisioning_adapter.codec import VmAnsibleCodec
from compute_provisioning.jobs.queue import AsyncJobQueue
from compute_provisioning.hosts import ConnectionCodecs
from compute_provisioning.hosts.service import HostAuthority
from compute_provisioning_ansible import SshConnectionCodec
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning_service.services.job_retry import retry_policy_from
from vm_provisioning_adapter.services.job_submitter import VmJobSubmitter
from compute_provisioning.jobs.executor_mock import MockRule
from compute_provisioning_ansible import MockAnsibleRunner
from vm_provisioning_adapter.services.mock_output import vm_mock_output
from vm_provisioning_adapter.services.system_service import SystemService

HOST = "kvm1"


@pytest.fixture
def db_engine(tmp_path):
    """Use file-backed SQLite because this module runs DB sessions concurrently."""

    engine = create_db_engine(
        f"sqlite:///{tmp_path / 'test-controller.db'}",
        is_sqlite=True,
    )
    _initialize_test_database(engine)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# AsyncProvisioningTestClient
#
# The canonical ProvisioningTestClient (e2e-tests/src/e2e_harness/) is sync-only.
# This async variant is backed by the same ASGITransport as the main
# the canonical clients so all calls share the in-process app.  No raw HTTP
# calls appear in test bodies — all test code calls named methods here.
# ---------------------------------------------------------------------------

from .conftest import AsyncProvisioningTestClient, AsyncProvisioningTestClientError
@pytest.fixture
def programmable_mock() -> MockAnsibleRunner:
    svc = MockAnsibleRunner(default_output=vm_mock_output)
    import tempfile
    fake_inv = Path(tempfile.gettempdir()) / "test_inv.ini"
    fake_inv.write_text("[kvm_hosts]\nkvm1  ansible_host=10.0.0.1  ansible_user=root\n")
    svc.write_inventory = MagicMock(return_value=MaterializedInventory(path=fake_inv))
    svc.check_connectivity_with_inventory = AsyncMock(
        return_value=MagicMock(reachable=True, detail="mock ping ok")
    )
    return svc


@pytest_asyncio.fixture
async def client_and_queue(
    session_factory,
    programmable_mock,
    monkeypatch,
    job_executor_table_for,
) -> AsyncIterator[tuple[ProvisioningClients, AsyncJobQueue, MockAnsibleRunner, AsyncProvisioningTestClient]]:
    _install_signed_asgi_transport(monkeypatch)
    mock_settings = MagicMock(
        default_host_id="kvm1",
        default_max_retries=3,
        retry_backoff_initial_seconds=60,
        retry_backoff_multiplier=2.0,
        retry_backoff_max_seconds=3600,
        ansible_timeout_seconds=30,
        additional_non_retryable_errors=["UNREACHABLE"],
        frp_server_addr="",
        frp_domain="",
        frp_dashboard_password="",
        resolved_playbook_path=Path("/fake/playbook.yml"),
        resolved_inventory_path=Path("/fake/hosts"),
        ssh_decryption_key="",
        database_url="sqlite:///:memory:",
    )
    identity_context = ProvisioningIdentityContext(
        signer=SERVICE_SIGNER,
        storefront_principal=STOREFRONT_SIGNER.identity,
        admin_principal=ADMIN_SIGNER.identity,
        storefront_site_id="default",
    )
    principal_authority = SqlAlchemyProvisioningPrincipalAuthority(
        session_factory,
        identity_context,
    )
    replay_store = SqlAlchemyProvisioningReplayStore(session_factory)
    app.container.identity_context.override(identity_context)
    app.container.principal_authority.override(principal_authority)
    app.container.provisioning_replay_store.override(replay_store)

    host_authority = HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([SshConnectionCodec()]),
        capacity_derivation=LegacyHostCapacityDerivation(
            CapacityLedgerService(
                session_factory,
                unit_claim_keys=("units", "gpu_count"),
                mirror_dimension="gpu_count",
            )
        ),
    )
    from compute_provisioning_contracts import HostCreate
    host_authority.register_host(HostCreate(
        host_id=HOST,
        connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="root", key_path="~/.ssh/id_ed25519"),
        gpu_count=0,
    ))

    job_engine = JobEngine(
        session_factory,
        executors=job_executor_table_for(programmable_mock, mock_settings),
        host_lookup=host_authority.lookup,
        retry_policy=retry_policy_from(mock_settings),
    )
    job_submitter = VmJobSubmitter(job_engine, default_host_id=mock_settings.default_host_id)
    system_service = SystemService(
        ansible_service=programmable_mock,
        settings=mock_settings,
        host_service=host_authority,
    )
    job_queue = AsyncJobQueue(max_concurrent=2)

    from vm_provisioning_adapter.runtime import VmProvisioningRuntime
    from vm_provisioning_adapter.services.ansible_pool_config_handler import (
        AnsiblePoolConfigHandler,
    )
    from vm_provisioning_adapter.services.host_operations_service import (
        HostOperationsService,
    )
    from vm_provisioning_adapter.services.vm_operations_service import (
        VmOperationsService,
    )
    from market_fulfillment import SettlementRepository

    def _unused_fulfillment_service_provider():
        raise RuntimeError(
            "fulfillment_service is not wired in this fixture — "
            "these tests do not exercise VM release/teardown"
        )

    vm_runtime = VmProvisioningRuntime(
        config=mock_settings,
        session_factory=session_factory,
        job_queue_provider=lambda: job_queue,
        ansible_service=programmable_mock,
        codec=VmAnsibleCodec(),
        host_authority=host_authority,
        pool_config_handler=AnsiblePoolConfigHandler(),
        job_engine=job_engine,
        job_submitter=job_submitter,
        vm_operations_service=VmOperationsService(
            job_submitter=job_submitter,
            job_queue_provider=lambda: job_queue,
        ),
        host_operations_service=HostOperationsService(
            host_service=host_authority,
            job_submitter=job_submitter,
            job_queue_provider=lambda: job_queue,
        ),
        settlement_repository=SettlementRepository(),
        teardown_port=object(),
    )

    app.container.vm_runtime.override(vm_runtime)
    app.container.ansible_service.override(programmable_mock)
    app.container.job_engine.override(job_engine)
    app.container.system_service.override(system_service)
    app.container.session_factory.override(session_factory)
    app.container.host_authority.override(host_authority)

    _container_module.resolved_job_engine = job_engine
    _container_module.resolved_session_factory = session_factory
    _container_module.resolved_ansible_service = programmable_mock
    _container_module.resolved_system_service = system_service
    _container_module.resolved_host_authority = host_authority

    from vm_provisioning_adapter.controllers.test_controller import make_router as _make_test_router
    _test_prefix = "/test"
    _already_mounted = any(
        getattr(r, "path", "").startswith(_test_prefix) for r in app.routes
    )
    if not _already_mounted:
        from compute_provisioning_service.controllers import test_jobs_controller

        app.include_router(test_jobs_controller.router)
        app.include_router(_make_test_router())

    _container_module.resolved_job_queue = job_queue
    _container_module.resolved_vm_operations_service = app.container.vm_operations_service()
    _container_module.resolved_host_operations_service = app.container.host_operations_service()

    processing_task = asyncio.create_task(
        job_queue.start(job_engine.process_job),
        name="test-job-processing-loop",
    )

    transport = ASGITransport(app=app)
    prov_client = provisioning_clients(transport)
    test_client = AsyncProvisioningTestClient(transport)

    yield prov_client, job_queue, programmable_mock, test_client

    await test_client.close()
    processing_task.cancel()
    try:
        await processing_task
    except asyncio.CancelledError:
        pass

    app.container.vm_runtime.reset_override()
    app.container.identity_context.reset_override()
    app.container.principal_authority.reset_override()
    app.container.provisioning_replay_store.reset_override()
    app.container.ansible_service.reset_override()
    app.container.job_engine.reset_override()
    app.container.system_service.reset_override()
    app.container.session_factory.reset_override()
    app.container.host_authority.reset_override()
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
        submit = await prov_client.vm.create_vm(HOST, CreateVmRequest(
            vm_target="test-vm", vm_ram=2048, vm_vcpus=2,
            vm_disk_size="20G", ssh_pubkey="ssh-ed25519 AAAA test",
        ))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        await prov_client.family.poll_until_complete(submit.job_id, timeout=10.0)
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
        await prov_client.vm.create_vm(HOST, CreateVmRequest(
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
        submit = await prov_client.vm.create_vm(HOST, CreateVmRequest(
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
        submit = await prov_client.vm.create_vm(HOST, CreateVmRequest(
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
        _container_module.resolved_ansible_service = MagicMock(spec=AnsibleRunner)
        try:
            with pytest.raises(AsyncProvisioningTestClientError) as exc_info:
                await test_client.add_mock_rule(match={})
            assert exc_info.value.status_code == 503
        finally:
            _container_module.resolved_ansible_service = original
