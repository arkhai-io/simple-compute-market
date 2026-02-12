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
from async_provisioning_service.db.models import Base, JobStatus, ProvisioningJob


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_1 = "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
AGENT_2 = "eip155:31337:0x70997970C51812dc3A010C7d01b50e0d17dc79C8:2"

PROVISION_PAYLOAD = {"vm_target": "tenant-vm", "ssh_pubkey": "ssh-rsa AAAA-test-key"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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

    # Auth middleware in disabled mode -- still extracts X-Agent-ID if present
    application.add_middleware(AgentAuthMiddleware, enabled=False)

    application.include_router(router)

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass  # session lifecycle managed by fixture

    application.dependency_overrides[get_db] = _override_get_db
    return application


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


# ---------------------------------------------------------------------------
# Submit job tests
# ---------------------------------------------------------------------------


class TestSubmitJob:
    @pytest.mark.anyio
    async def test_submit_job_stores_agent_id(self, app, db_session):
        """POST /provision with X-Agent-ID stores the agent on the job."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "async_provisioning_service.services.queue.enqueue_job",
                lambda *a, **kw: _async_noop(),
            )
            # Also patch at the routes level where it is imported
            mp.setattr(
                "async_provisioning_service.api.routes.enqueue_job",
                lambda *a, **kw: _async_noop(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
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
    async def test_submit_job_without_agent_id(self, app, db_session):
        """POST /provision without header stores agent_id as None."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "async_provisioning_service.services.queue.enqueue_job",
                lambda *a, **kw: _async_noop(),
            )
            mp.setattr(
                "async_provisioning_service.api.routes.enqueue_job",
                lambda *a, **kw: _async_noop(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/provision", json=PROVISION_PAYLOAD)

        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = db_session.query(ProvisioningJob).filter_by(id=job_id).one()
        assert job.agent_id is None


# ---------------------------------------------------------------------------
# List jobs tests
# ---------------------------------------------------------------------------


class TestListJobs:
    @pytest.mark.anyio
    async def test_list_jobs_all(self, app, seeded_jobs):
        """GET /provision without agent header returns all jobs."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/provision")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6  # 3 agent1 + 2 agent2 + 1 anon

    @pytest.mark.anyio
    async def test_list_jobs_filtered_by_agent(self, app, seeded_jobs):
        """GET /provision with X-Agent-ID returns only that agent's jobs."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/provision",
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        for job in data["jobs"]:
            assert job["agent_id"] == AGENT_1

    @pytest.mark.anyio
    async def test_list_jobs_pagination(self, app, seeded_jobs):
        """Offset/limit query params correctly paginate results."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/provision", params={"offset": 0, "limit": 2})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert len(data["jobs"]) == 2
        assert data["offset"] == 0
        assert data["limit"] == 2

    @pytest.mark.anyio
    async def test_list_jobs_pagination_offset(self, app, seeded_jobs):
        """Non-zero offset skips earlier results."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/provision", params={"offset": 4, "limit": 10})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert len(data["jobs"]) == 2  # only 2 remaining after offset 4

    @pytest.mark.anyio
    async def test_list_jobs_status_filter(self, app, seeded_jobs):
        """Filter by status returns only matching jobs."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/provision", params={"status": "queued"})

        assert resp.status_code == 200
        data = resp.json()
        # agent1_queued + agent2_queued + anon_queued = 3
        assert data["total"] == 3
        for job in data["jobs"]:
            assert job["status"] == "queued"

    @pytest.mark.anyio
    async def test_list_jobs_status_and_agent_filter(self, app, seeded_jobs):
        """Combining agent and status filters narrows results correctly."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
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


# ---------------------------------------------------------------------------
# Get status tests
# ---------------------------------------------------------------------------


class TestGetStatus:
    @pytest.mark.anyio
    async def test_get_status_includes_agent_id(self, app, seeded_jobs):
        """GET /provision/{job_id} includes agent_id in the response."""
        job_id = seeded_jobs["agent1_queued"]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/provision/{job_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["agent_id"] == AGENT_1

    @pytest.mark.anyio
    async def test_get_status_not_found(self, app, seeded_jobs):
        """GET /provision/{nonexistent} returns 404."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/provision/{uuid.uuid4()}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cancel job tests
# ---------------------------------------------------------------------------


class TestCancelJob:
    @pytest.mark.anyio
    async def test_cancel_own_job(self, app, seeded_jobs):
        """Agent cancels their own queued job -- succeeds."""
        job_id = seeded_jobs["agent1_queued"]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/provision/{job_id}/cancel",
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["message"] == "Job cancelled successfully"

    @pytest.mark.anyio
    async def test_cancel_other_agents_job(self, app, seeded_jobs):
        """Agent tries to cancel another agent's job -- returns 403."""
        job_id = seeded_jobs["agent1_queued"]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/provision/{job_id}/cancel",
                headers={"X-Agent-ID": AGENT_2},
            )

        assert resp.status_code == 403
        assert "Cannot cancel another agent's job" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_cancel_without_agent_id(self, app, seeded_jobs):
        """Cancel without agent_id (auth disabled) succeeds for any job."""
        job_id = seeded_jobs["agent1_queued"]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/provision/{job_id}/cancel")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"

    @pytest.mark.anyio
    async def test_cancel_nonexistent_job(self, app, seeded_jobs):
        """Cancelling a non-existent job returns 404."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/provision/{uuid.uuid4()}/cancel")

        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_cancel_already_succeeded_job(self, app, seeded_jobs):
        """Cancelling a succeeded job returns non-cancellable message."""
        job_id = seeded_jobs["agent1_succeeded"]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/provision/{job_id}/cancel",
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "succeeded"
        assert "cannot be cancelled" in data["message"].lower()


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestProvisionSchema:
    def test_provision_request_no_root_ssh_fields(self):
        """ProvisionRequest should NOT accept root_ssh_filename or root_ssh_password."""
        req = ProvisionRequest(vm_target="tenant-vm")
        dumped = req.model_dump()
        assert "root_ssh_filename" not in dumped
        assert "root_ssh_password" not in dumped

    def test_provision_request_defaults(self):
        """Verify sensible defaults for ProvisionRequest."""
        req = ProvisionRequest(vm_target="tenant-vm")
        assert req.vm_host == "ww1"
        assert req.vm_target == "tenant-vm"
        assert req.vm_action == "create"
        assert req.vm_ram is None
        assert req.vm_vcpus is None
        assert req.vm_disk_size is None
        assert req.image_setup_type == "scratch"
        assert req.ssh_pubkey is None
        assert req.max_retries is None

    def test_provision_request_image_setup_type_validation(self):
        """Only 'scratch' and 'golden' are valid image_setup_type values."""
        # Valid values
        req1 = ProvisionRequest(vm_target="tenant-vm", image_setup_type="scratch")
        assert req1.image_setup_type == "scratch"

        req2 = ProvisionRequest(vm_target="tenant-vm", image_setup_type="golden")
        assert req2.image_setup_type == "golden"

        # Invalid value
        with pytest.raises(Exception):  # Pydantic ValidationError
            ProvisionRequest(vm_target="tenant-vm", image_setup_type="custom")

    def test_provision_request_vm_target_required_for_create(self):
        """vm_target is required for create action."""
        with pytest.raises(Exception):
            ProvisionRequest(vm_action="create")

    def test_provision_request_vm_target_not_required_for_list(self):
        """vm_target is NOT required for list action."""
        req = ProvisionRequest(vm_action="list")
        assert req.vm_target is None

    def test_provision_request_vm_target_not_required_for_check(self):
        """vm_target is NOT required for check action."""
        req = ProvisionRequest(vm_action="check")
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

    def test_provision_request_vm_action_constrained(self):
        """vm_action only accepts valid action literals."""
        with pytest.raises(Exception):
            ProvisionRequest(vm_target="my-vm", vm_action="invalid_action")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_noop(*args, **kwargs):
    """Async no-op used to replace enqueue_job."""
    pass
