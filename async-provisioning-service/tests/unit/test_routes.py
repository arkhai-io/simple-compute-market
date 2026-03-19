from unittest.mock import AsyncMock, patch

from async_provisioning_service.db.models import Credential, JobStatus, ProvisioningJob


SELLER_AGENT_ID = "eip155:84532:0x1111111111111111111111111111111111111111:7"
BUYER_AGENT_ID = "eip155:84532:0x2222222222222222222222222222222222222222:8"
OTHER_AGENT_ID = "eip155:84532:0x3333333333333333333333333333333333333333:9"


def test_submit_job_persists_seller_and_buyer_ids(client_factory, db_session):
    with patch("async_provisioning_service.api.routes.enqueue_job", AsyncMock()) as enqueue_job:
        with client_factory(auth_enabled=False) as client:
            response = client.post(
                "/api/v1/jobs",
                json={
                    "vm_host": "ww1",
                    "vm_action": "check",
                    "buyer_agent_id": BUYER_AGENT_ID,
                },
                headers={"X-Agent-ID": SELLER_AGENT_ID},
            )

    assert response.status_code == 202
    job = db_session.query(ProvisioningJob).one()
    assert job.agent_id == SELLER_AGENT_ID
    assert job.buyer_agent_id == BUYER_AGENT_ID
    enqueue_job.assert_awaited_once_with(job.id)


def test_get_status_allows_buyer_to_view_job(client_factory, db_session):
    job = ProvisioningJob(
        id="job-1",
        status=JobStatus.succeeded.value,
        params={"vm_action": "check"},
        agent_id=SELLER_AGENT_ID,
        buyer_agent_id=BUYER_AGENT_ID,
    )
    db_session.add(job)
    db_session.commit()

    with client_factory(auth_enabled=False) as client:
        response = client.get(
            "/api/v1/jobs/job-1",
            headers={"X-Agent-ID": BUYER_AGENT_ID},
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"


def test_get_status_denies_unrelated_agent(client_factory, db_session):
    job = ProvisioningJob(
        id="job-2",
        status=JobStatus.running.value,
        params={"vm_action": "check"},
        agent_id=SELLER_AGENT_ID,
        buyer_agent_id=BUYER_AGENT_ID,
    )
    db_session.add(job)
    db_session.commit()

    with client_factory(auth_enabled=False) as client:
        response = client.get(
            "/api/v1/jobs/job-2",
            headers={"X-Agent-ID": OTHER_AGENT_ID},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied: job belongs to another agent"


def test_get_credentials_requires_header(client_factory, db_session):
    job = ProvisioningJob(
        id="job-3",
        status=JobStatus.succeeded.value,
        params={"vm_action": "check"},
        agent_id=SELLER_AGENT_ID,
        buyer_agent_id=BUYER_AGENT_ID,
    )
    db_session.add(job)
    db_session.commit()

    with client_factory(auth_enabled=False) as client:
        response = client.get("/api/v1/jobs/job-3/credentials")

    assert response.status_code == 401
    assert response.json()["detail"] == "X-Agent-ID header is required"


def test_get_credentials_returns_only_credentials_granted_to_requesting_agent(client_factory, db_session):
    job = ProvisioningJob(
        id="job-4",
        status=JobStatus.succeeded.value,
        params={"vm_action": "create"},
        agent_id=SELLER_AGENT_ID,
        buyer_agent_id=BUYER_AGENT_ID,
    )
    db_session.add(job)
    db_session.add(
        Credential(
            job_id="job-4",
            role="root",
            granted_to=SELLER_AGENT_ID,
            password="seller-root-pass",
        )
    )
    db_session.add(
        Credential(
            job_id="job-4",
            role="tenant",
            granted_to=BUYER_AGENT_ID,
            password="buyer-tenant-pass",
        )
    )
    db_session.commit()

    with client_factory(auth_enabled=False) as client:
        response = client.get(
            "/api/v1/jobs/job-4/credentials",
            headers={"X-Agent-ID": BUYER_AGENT_ID},
        )

    assert response.status_code == 200
    credentials = response.json()["credentials"]
    assert len(credentials) == 1
    assert credentials[0]["role"] == "tenant"
    assert credentials[0]["password"] == "buyer-tenant-pass"
