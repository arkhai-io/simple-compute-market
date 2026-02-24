"""Unit tests for multi-agent route behaviour.

Tests the provisioning API routes with focus on agent_id scoping,
ownership enforcement, pagination, and schema validation. Uses an
in-memory SQLite database and disables auth to isolate route logic.
"""

import uuid
from unittest.mock import patch

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
    application.include_router(router, prefix="/api/v1")

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
                "/api/v1/jobs",
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
            resp = await client.post("/api/v1/jobs", json=PROVISION_PAYLOAD)

        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = db_session.query(ProvisioningJob).filter_by(id=job_id).one()
        assert job.agent_id is None


class TestListJobs:
    @pytest.mark.anyio
    async def test_list_jobs_all(self, client, seeded_jobs):
        """GET /provision without agent header returns all jobs."""
        async with client:
            resp = await client.get("/api/v1/jobs")

        assert resp.status_code == 200
        assert resp.json()["total"] == 6

    @pytest.mark.anyio
    async def test_list_jobs_filtered_by_agent(self, client, seeded_jobs):
        """GET /provision with X-Agent-ID returns only that agent's jobs."""
        async with client:
            resp = await client.get("/api/v1/jobs", headers={"X-Agent-ID": AGENT_1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        for job in data["jobs"]:
            assert job["agent_id"] == AGENT_1

    @pytest.mark.anyio
    async def test_list_jobs_pagination(self, client, seeded_jobs):
        """Offset/limit query params correctly paginate results."""
        async with client:
            resp = await client.get("/api/v1/jobs", params={"offset": 0, "limit": 2})

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
            resp = await client.get("/api/v1/jobs", params={"offset": 4, "limit": 10})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert len(data["jobs"]) == 2

    @pytest.mark.anyio
    async def test_list_jobs_status_filter(self, client, seeded_jobs):
        """Filter by status returns only matching jobs."""
        async with client:
            resp = await client.get("/api/v1/jobs", params={"status": "queued"})

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
                "/api/v1/jobs",
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
                f"/api/v1/jobs/{job_id}",
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
            resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")

        assert resp.status_code == 404


class TestCancelJob:
    @pytest.mark.anyio
    async def test_cancel_own_job(self, client, seeded_jobs):
        """Agent cancels their own queued job -- succeeds."""
        job_id = seeded_jobs["agent1_queued"]
        async with client:
            resp = await client.post(
                f"/api/v1/jobs/{job_id}/cancel",
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
                f"/api/v1/jobs/{job_id}/cancel",
                headers={"X-Agent-ID": AGENT_2},
            )

        assert resp.status_code == 403
        assert "Cannot cancel another agent's job" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_cancel_without_agent_id(self, client, seeded_jobs):
        """Cancel without agent_id (auth disabled) succeeds for any job."""
        job_id = seeded_jobs["agent1_queued"]
        async with client:
            resp = await client.post(f"/api/v1/jobs/{job_id}/cancel")

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.anyio
    async def test_cancel_nonexistent_job(self, client, seeded_jobs):
        """Cancelling a non-existent job returns 404."""
        async with client:
            resp = await client.post(f"/api/v1/jobs/{uuid.uuid4()}/cancel")

        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_cancel_already_succeeded_job(self, client, seeded_jobs):
        """Cancelling a succeeded job returns non-cancellable message."""
        job_id = seeded_jobs["agent1_succeeded"]
        async with client:
            resp = await client.post(
                f"/api/v1/jobs/{job_id}/cancel",
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


@pytest.fixture()
def job_with_credentials(db_session, seeded_jobs):
    """Seed Credential rows for agent1_succeeded job with AGENT_2 as buyer."""
    from async_provisioning_service.db.models import Credential, CredentialRole

    job_id = seeded_jobs["agent1_succeeded"]
    job = db_session.query(ProvisioningJob).filter_by(id=job_id).one()
    job.buyer_agent_id = AGENT_2

    db_session.add(Credential(
        job_id=job_id, role=CredentialRole.root.value,
        granted_to=AGENT_1, password="root-pass",
        ssh_commands={"external": "ssh root@host"},
        ssh_key_path_host="/path/to/key", key_type="provided",
    ))
    db_session.add(Credential(
        job_id=job_id, role=CredentialRole.tenant.value,
        granted_to=AGENT_1, password="tenant-pass-seller",
        ssh_commands={"external": "ssh ubuntu@host"},
    ))
    db_session.add(Credential(
        job_id=job_id, role=CredentialRole.tenant.value,
        granted_to=AGENT_2, password="tenant-pass-buyer",
        ssh_commands={"external": "ssh ubuntu@host"},
    ))
    db_session.commit()
    return job_id


class TestHealthEndpoint:
    @pytest.fixture()
    def health_app(self, db_session):
        from async_provisioning_service.api.routes import health_router
        application = FastAPI()
        application.include_router(health_router)

        def _override_get_db():
            yield db_session

        application.dependency_overrides[get_db] = _override_get_db
        return application

    @pytest.fixture()
    def health_client(self, health_app):
        transport = httpx.ASGITransport(app=health_app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    @pytest.mark.anyio
    async def test_health_ok(self, health_client, monkeypatch):
        """Health returns 200 when DB and Redis are OK."""
        from unittest.mock import AsyncMock, patch
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        with patch("async_provisioning_service.api.routes.get_redis", AsyncMock(return_value=mock_redis)):
            async with health_client as client:
                resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.anyio
    async def test_health_db_failure(self, health_app, db_session, monkeypatch):
        """Health returns 503 when DB fails."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from sqlalchemy import exc as sa_exc

        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True

        # Make db.execute raise
        original_execute = db_session.execute

        def failing_execute(*args, **kwargs):
            raise sa_exc.OperationalError("SELECT 1", {}, Exception("connection failed"))

        db_session.execute = failing_execute

        with patch("async_provisioning_service.api.routes.get_redis", AsyncMock(return_value=mock_redis)):
            transport = httpx.ASGITransport(app=health_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")

        db_session.execute = original_execute
        assert resp.status_code == 503

    @pytest.mark.anyio
    async def test_health_redis_failure(self, health_client, monkeypatch):
        """Health returns 503 when Redis fails."""
        from unittest.mock import AsyncMock, patch
        mock_redis = AsyncMock()
        mock_redis.ping.side_effect = Exception("redis connection refused")
        with patch("async_provisioning_service.api.routes.get_redis", AsyncMock(return_value=mock_redis)):
            async with health_client as client:
                resp = await client.get("/health")
        assert resp.status_code == 503


class TestGetCredentials:
    @pytest.mark.anyio
    async def test_no_agent_id_returns_401(self, client, job_with_credentials):
        job_id = job_with_credentials
        async with client as c:
            resp = await c.get(f"/api/v1/jobs/{job_id}/credentials")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_unauthorized_agent_returns_403(self, client, job_with_credentials):
        """An agent that is neither seller nor buyer gets 403."""
        AGENT_3 = "eip155:31337:0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC:3"
        job_id = job_with_credentials
        async with client as c:
            resp = await c.get(
                f"/api/v1/jobs/{job_id}/credentials",
                headers={"X-Agent-ID": AGENT_3},
            )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_job_not_found_returns_404(self, client, job_with_credentials):
        async with client as c:
            resp = await c.get(
                f"/api/v1/jobs/{uuid.uuid4()}/credentials",
                headers={"X-Agent-ID": AGENT_1},
            )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_seller_gets_root_and_tenant(self, client, job_with_credentials):
        job_id = job_with_credentials
        async with client as c:
            resp = await c.get(
                f"/api/v1/jobs/{job_id}/credentials",
                headers={"X-Agent-ID": AGENT_1},
            )
        assert resp.status_code == 200
        data = resp.json()
        roles = [c["role"] for c in data["credentials"]]
        assert "root" in roles
        assert "tenant" in roles

    @pytest.mark.anyio
    async def test_buyer_gets_tenant_only(self, client, job_with_credentials):
        job_id = job_with_credentials
        async with client as c:
            resp = await c.get(
                f"/api/v1/jobs/{job_id}/credentials",
                headers={"X-Agent-ID": AGENT_2},
            )
        assert resp.status_code == 200
        data = resp.json()
        roles = [c["role"] for c in data["credentials"]]
        assert roles == ["tenant"]


class TestGetLogs:
    @pytest.mark.anyio
    async def test_get_logs_unauthorized_returns_403(self, client, seeded_jobs):
        """AGENT_2 trying to access AGENT_1's job logs -> 403."""
        job_id = seeded_jobs["agent1_queued"]
        async with client as c:
            resp = await c.get(
                f"/api/v1/jobs/{job_id}/logs",
                headers={"X-Agent-ID": AGENT_2},
            )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_get_logs_authorized_returns_200(self, client, seeded_jobs):
        """AGENT_1 accessing their own job logs -> 200."""
        job_id = seeded_jobs["agent1_queued"]
        async with client as c:
            resp = await c.get(
                f"/api/v1/jobs/{job_id}/logs",
                headers={"X-Agent-ID": AGENT_1},
            )
        assert resp.status_code == 200
        assert "job_id" in resp.json()


# ---------------------------------------------------------------------------
# Extensions to TestCancelJob
# ---------------------------------------------------------------------------

class TestCancelJobExtended:
    @pytest.mark.anyio
    async def test_cancel_running_job_sends_sigterm(self, client, db_session, seeded_jobs):
        """Running job with process_id -> SIGTERM sent -> job cancelled."""
        import os
        import signal

        job_id = seeded_jobs["agent1_running"]
        job = db_session.query(ProvisioningJob).filter_by(id=job_id).one()
        job.process_id = "12345"
        db_session.commit()

        with patch("async_provisioning_service.api.routes.os.kill") as mock_kill:
            async with client as c:
                resp = await c.post(
                    f"/api/v1/jobs/{job_id}/cancel",
                    headers={"X-Agent-ID": AGENT_1},
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    @pytest.mark.anyio
    async def test_cancel_running_job_process_not_found(self, client, db_session, seeded_jobs):
        """ProcessLookupError on os.kill -> still returns 200 cancelled."""
        job_id = seeded_jobs["agent1_running"]
        job = db_session.query(ProvisioningJob).filter_by(id=job_id).one()
        job.process_id = "99999"
        db_session.commit()

        with patch("async_provisioning_service.api.routes.os.kill", side_effect=ProcessLookupError()):
            async with client as c:
                resp = await c.post(
                    f"/api/v1/jobs/{job_id}/cancel",
                    headers={"X-Agent-ID": AGENT_1},
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.anyio
    async def test_cancel_running_job_invalid_pid(self, client, db_session, seeded_jobs):
        """Invalid process_id string -> ValueError path -> still 200 cancelled."""
        job_id = seeded_jobs["agent1_running"]
        job = db_session.query(ProvisioningJob).filter_by(id=job_id).one()
        job.process_id = "not-a-number"
        db_session.commit()

        async with client as c:
            resp = await c.post(
                f"/api/v1/jobs/{job_id}/cancel",
                headers={"X-Agent-ID": AGENT_1},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
