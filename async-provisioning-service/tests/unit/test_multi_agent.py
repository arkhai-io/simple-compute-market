"""Unit tests for multi-agent route behaviour.

Tests the provisioning API routes with focus on agent_id scoping,
ownership enforcement, pagination, and schema validation. Uses an
in-memory SQLite database and disables auth to isolate route logic.
"""

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from async_provisioning_service.api.auth import AgentAuthMiddleware
from async_provisioning_service.api.routes import router
from async_provisioning_service.api.schemas import ProvisionRequest
from async_provisioning_service.db.database import get_db
from async_provisioning_service.db.models import Base, JobStatus, ProvisionedVM, ProvisioningJob

AGENT_1 = "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
AGENT_2 = "eip155:31337:0x70997970C51812dc3A010C7d01b50e0d17dc79C8:2"

PROVISION_PAYLOAD = {"vm_target": "tenant-vm", "ssh_pubkey": "ssh-rsa AAAA-test-key"}


async def _async_noop(*args, **kwargs):
    pass


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite engine + session for each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def app(db_session: Session):
    """Build a FastAPI app with auth DISABLED and DB dependency overridden."""
    application = FastAPI()
    application.add_middleware(AgentAuthMiddleware, enabled=False)
    application.include_router(router)

    def _override_get_db():
        yield db_session

    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest.fixture()
def client(app):
    """Yield an httpx.AsyncClient wired to the ASGI app."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture()
def seeded_jobs(db_session: Session) -> dict[str, str]:
    """Seed the database with jobs from two agents and one anonymous job.

    Returns a mapping of logical names to job IDs.
    """
    jobs = {}
    for name, agent_id, status_val in [
        ("agent1_queued", AGENT_1, JobStatus.queued.value),
        ("agent1_running", AGENT_1, JobStatus.running.value),
        ("agent1_succeeded", AGENT_1, JobStatus.succeeded.value),
        ("agent2_queued", AGENT_2, JobStatus.queued.value),
        ("agent2_failed", AGENT_2, JobStatus.failed.value),
        ("anon_queued", None, JobStatus.queued.value),
    ]:
        job_id = str(uuid.uuid4())
        job = ProvisioningJob(
            id=job_id,
            status=status_val,
            params={"vm_target": "tenant-vm", "ssh_pubkey": "ssh-rsa test", "vm_host": "ww1"},
            agent_id=agent_id,
            retry_count=0,
            max_retries=3,
        )
        db_session.add(job)
        jobs[name] = job_id

    db_session.commit()
    return jobs


@pytest.fixture()
def patch_enqueue(monkeypatch):
    """Stub out enqueue_job at both import locations."""
    monkeypatch.setattr(
        "async_provisioning_service.services.queue.enqueue_job",
        lambda *a, **kw: _async_noop(),
    )
    monkeypatch.setattr(
        "async_provisioning_service.api.routes.enqueue_job",
        lambda *a, **kw: _async_noop(),
    )


class TestSubmitJob:
    @pytest.mark.anyio
    async def test_submit_job_stores_agent_id(self, client, db_session, patch_enqueue):
        """POST /provision with X-Agent-ID stores the agent on the job."""
        async with client:
            resp = await client.post(
                "/provision",
                json=PROVISION_PAYLOAD,
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = db_session.query(ProvisioningJob).filter_by(id=job_id).one()
        assert job.agent_id == AGENT_1

    @pytest.mark.anyio
    async def test_submit_job_without_agent_id(self, client, db_session, patch_enqueue):
        """POST /provision without header stores agent_id as None."""
        async with client:
            resp = await client.post("/provision", json=PROVISION_PAYLOAD)

        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = db_session.query(ProvisioningJob).filter_by(id=job_id).one()
        assert job.agent_id is None


class TestListJobs:
    @pytest.mark.anyio
    async def test_list_jobs_all(self, client, seeded_jobs):
        """GET /provision without agent header returns all jobs."""
        async with client:
            resp = await client.get("/provision")

        assert resp.status_code == 200
        assert resp.json()["total"] == 6

    @pytest.mark.anyio
    async def test_list_jobs_filtered_by_agent(self, client, seeded_jobs):
        """GET /provision with X-Agent-ID returns only that agent's jobs."""
        async with client:
            resp = await client.get("/provision", headers={"X-Agent-ID": AGENT_1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        for job in data["jobs"]:
            assert job["agent_id"] == AGENT_1

    @pytest.mark.anyio
    async def test_list_jobs_pagination(self, client, seeded_jobs):
        """Offset/limit query params correctly paginate results."""
        async with client:
            resp = await client.get("/provision", params={"offset": 0, "limit": 2})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert len(data["jobs"]) == 2
        assert data["offset"] == 0
        assert data["limit"] == 2

    @pytest.mark.anyio
    async def test_list_jobs_pagination_offset(self, client, seeded_jobs):
        """Non-zero offset skips earlier results."""
        async with client:
            resp = await client.get("/provision", params={"offset": 4, "limit": 10})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert len(data["jobs"]) == 2

    @pytest.mark.anyio
    async def test_list_jobs_status_filter(self, client, seeded_jobs):
        """Filter by status returns only matching jobs."""
        async with client:
            resp = await client.get("/provision", params={"status": "queued"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        for job in data["jobs"]:
            assert job["status"] == "queued"

    @pytest.mark.anyio
    async def test_list_jobs_status_and_agent_filter(self, client, seeded_jobs):
        """Combining agent and status filters narrows results correctly."""
        async with client:
            resp = await client.get(
                "/provision",
                params={"status": "queued"},
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["jobs"][0]["status"] == "queued"
        assert data["jobs"][0]["agent_id"] == AGENT_1


class TestGetStatus:
    @pytest.mark.anyio
    async def test_get_status_includes_agent_id(self, client, seeded_jobs):
        """GET /provision/{job_id} includes agent_id in the response."""
        job_id = seeded_jobs["agent1_queued"]
        async with client:
            resp = await client.get(
                f"/provision/{job_id}",
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["agent_id"] == AGENT_1

    @pytest.mark.anyio
    async def test_get_status_not_found(self, client, seeded_jobs):
        """GET /provision/{nonexistent} returns 404."""
        async with client:
            resp = await client.get(f"/provision/{uuid.uuid4()}")

        assert resp.status_code == 404


class TestCancelJob:
    @pytest.mark.anyio
    async def test_cancel_own_job(self, client, seeded_jobs):
        """Agent cancels their own queued job -- succeeds."""
        job_id = seeded_jobs["agent1_queued"]
        async with client:
            resp = await client.post(
                f"/provision/{job_id}/cancel",
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["message"] == "Job cancelled successfully"

    @pytest.mark.anyio
    async def test_cancel_other_agents_job(self, client, seeded_jobs):
        """Agent tries to cancel another agent's job -- returns 403."""
        job_id = seeded_jobs["agent1_queued"]
        async with client:
            resp = await client.post(
                f"/provision/{job_id}/cancel",
                headers={"X-Agent-ID": AGENT_2},
            )

        assert resp.status_code == 403
        assert "Cannot cancel another agent's job" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_cancel_without_agent_id(self, client, seeded_jobs):
        """Cancel without agent_id (auth disabled) succeeds for any job."""
        job_id = seeded_jobs["agent1_queued"]
        async with client:
            resp = await client.post(f"/provision/{job_id}/cancel")

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.anyio
    async def test_cancel_nonexistent_job(self, client, seeded_jobs):
        """Cancelling a non-existent job returns 404."""
        async with client:
            resp = await client.post(f"/provision/{uuid.uuid4()}/cancel")

        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_cancel_already_succeeded_job(self, client, seeded_jobs):
        """Cancelling a succeeded job returns non-cancellable message."""
        job_id = seeded_jobs["agent1_succeeded"]
        async with client:
            resp = await client.post(
                f"/provision/{job_id}/cancel",
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "succeeded"
        assert "cannot be cancelled" in data["message"].lower()


class TestProvisionSchema:
    def test_provision_request_no_root_ssh_fields(self):
        """ProvisionRequest should NOT accept root_ssh_filename or root_ssh_password."""
        req = ProvisionRequest(vm_target="tenant-vm")
        dumped = req.model_dump()
        assert "root_ssh_filename" not in dumped
        assert "root_ssh_password" not in dumped

    @pytest.mark.parametrize(
        "action, should_raise",
        [
            pytest.param("create", True, id="create_requires_target"),
            pytest.param("list", False, id="list_no_target"),
            pytest.param("check", False, id="check_no_target"),
        ],
    )
    def test_provision_request_vm_target_requirement(self, action, should_raise):
        """vm_target is required for create but not for list/check."""
        if should_raise:
            with pytest.raises(Exception):
                ProvisionRequest(vm_action=action)
        else:
            req = ProvisionRequest(vm_action=action)
            assert req.vm_target is None

    def test_provision_request_lease_end_requires_vm_lease_end(self):
        """lease_end action requires vm_lease_end parameter."""
        with pytest.raises(Exception):
            ProvisionRequest(vm_action="lease_end", vm_target="my-vm")

    def test_provision_request_frp_requires_dashboard_password(self):
        """FRP server_addr requires dashboard_password."""
        with pytest.raises(Exception):
            ProvisionRequest(
                vm_target="my-vm",
                vm_action="create",
                frp_server_addr="10.0.0.1",
            )


# ---------------------------------------------------------------------------
# Provisioned VM Access (two-record model) tests
# ---------------------------------------------------------------------------

SELLER_ORDER = "order-seller-001"
BUYER_ORDER = "order-buyer-002"
VM_NAME = "test-vm-abc123"


@pytest.fixture()
def seeded_vms(db_session: Session) -> dict[str, str]:
    """Seed the database with seller + buyer ProvisionedVM access records.

    Returns a mapping of logical names to record IDs.
    """
    seller_id = str(uuid.uuid4())
    buyer_id = str(uuid.uuid4())

    seller_vm = ProvisionedVM(
        id=seller_id,
        job_id="job-001",
        vm_name=VM_NAME,
        vm_host="ww1",
        vm_ip_internal="192.168.1.10",
        vm_state="running",
        seller_order_id=SELLER_ORDER,
        buyer_order_id=BUYER_ORDER,
        role="seller",
        seller_agent_id=AGENT_1,
        buyer_agent_id=AGENT_2,
        negotiation_id="neg-001",
        escrow_uid="escrow-001",
        root_password="rootpass123",
        root_ssh_key_path="/root/.ssh/id_ed25519",
        root_ssh_commands={"internal": "ssh root@192.168.1.10", "external": "ssh -p 2222 root@example.com"},
        tenant_user="tenant",
        tenant_password="tenantpass456",
        tenant_ssh_commands={"internal": "ssh tenant@192.168.1.10", "external": "ssh -p 2222 tenant@example.com"},
        external_ssh_port="2222",
        frp_domain="example.com",
    )
    buyer_vm = ProvisionedVM(
        id=buyer_id,
        job_id="job-001",
        vm_name=VM_NAME,
        vm_host="ww1",
        vm_ip_internal="192.168.1.10",
        vm_state="running",
        seller_order_id=SELLER_ORDER,
        buyer_order_id=BUYER_ORDER,
        role="buyer",
        seller_agent_id=AGENT_1,
        buyer_agent_id=AGENT_2,
        negotiation_id="neg-001",
        escrow_uid="escrow-001",
        root_password=None,
        root_ssh_key_path=None,
        root_ssh_commands=None,
        tenant_user="tenant",
        tenant_password="tenantpass456",
        tenant_ssh_commands={"internal": "ssh tenant@192.168.1.10", "external": "ssh -p 2222 tenant@example.com"},
        external_ssh_port="2222",
        frp_domain="example.com",
    )
    db_session.add_all([seller_vm, buyer_vm])
    db_session.commit()
    return {"seller": seller_id, "buyer": buyer_id}


class TestProvisionedVMAccess:
    """Tests for the two-record provisioned_vm_access model."""

    @pytest.mark.anyio
    async def test_seller_finds_vm_by_seller_order_id(self, client, seeded_vms):
        """Seller queries by their order ID and sees root + tenant creds."""
        async with client:
            resp = await client.get(
                "/provisioned",
                params={"order_id": SELLER_ORDER},
                headers={"X-Agent-ID": AGENT_1},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        seller_vms = [v for v in data["vms"] if v["role"] == "seller"]
        assert len(seller_vms) == 1
        vm = seller_vms[0]
        assert vm["seller_order_id"] == SELLER_ORDER
        assert vm["root_password"] == "rootpass123"
        assert vm["root_ssh_key_path"] == "/root/.ssh/id_ed25519"
        assert vm["tenant_user"] == "tenant"
        assert vm["tenant_password"] == "tenantpass456"

    @pytest.mark.anyio
    async def test_buyer_finds_vm_by_buyer_order_id(self, client, seeded_vms):
        """Buyer queries by their order ID and sees only tenant creds (root fields None)."""
        async with client:
            resp = await client.get(
                "/provisioned",
                params={"order_id": BUYER_ORDER},
                headers={"X-Agent-ID": AGENT_2},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        buyer_vms = [v for v in data["vms"] if v["role"] == "buyer"]
        assert len(buyer_vms) == 1
        vm = buyer_vms[0]
        assert vm["buyer_order_id"] == BUYER_ORDER
        assert vm["root_password"] is None
        assert vm["root_ssh_key_path"] is None
        assert vm["root_ssh_commands"] is None
        assert vm["tenant_user"] == "tenant"
        assert vm["tenant_password"] == "tenantpass456"

    @pytest.mark.anyio
    async def test_cross_lookup_seller_queries_buyer_order(self, client, seeded_vms):
        """Seller queries with buyer's order_id — still finds their record."""
        async with client:
            resp = await client.get(
                "/provisioned",
                params={"order_id": BUYER_ORDER},
                headers={"X-Agent-ID": AGENT_1},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        seller_vms = [v for v in data["vms"] if v["role"] == "seller"]
        assert len(seller_vms) == 1

    @pytest.mark.anyio
    async def test_get_provisioned_vm_by_name_seller(self, client, seeded_vms):
        """GET /provisioned/{vm_name} with seller agent_id returns seller record."""
        async with client:
            resp = await client.get(
                f"/provisioned/{VM_NAME}",
                headers={"X-Agent-ID": AGENT_1},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["vm_name"] == VM_NAME
        assert data["role"] == "seller"
        assert data["root_password"] == "rootpass123"

    @pytest.mark.anyio
    async def test_get_provisioned_vm_by_name_buyer(self, client, seeded_vms):
        """GET /provisioned/{vm_name} with buyer agent_id returns buyer record."""
        async with client:
            resp = await client.get(
                f"/provisioned/{VM_NAME}",
                headers={"X-Agent-ID": AGENT_2},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["vm_name"] == VM_NAME
        assert data["role"] == "buyer"
        assert data["root_password"] is None
        assert data["tenant_user"] == "tenant"

    @pytest.mark.anyio
    async def test_get_provisioned_vm_unknown_agent_404(self, client, seeded_vms):
        """GET /provisioned/{vm_name} with unrelated agent returns 404."""
        async with client:
            resp = await client.get(
                f"/provisioned/{VM_NAME}",
                headers={"X-Agent-ID": "eip155:31337:0x1111111111111111111111111111111111111111:99"},
            )
        assert resp.status_code == 404
