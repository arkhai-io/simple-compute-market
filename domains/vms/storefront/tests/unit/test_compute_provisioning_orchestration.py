from types import SimpleNamespace

import pytest

from market_storefront.services import fulfillment_service
from market_storefront.services import provisioning_orchestration_service as orchestration


@pytest.mark.asyncio
async def test_vm_orchestration_submits_versioned_correlated_envelope(monkeypatch):
    captured = {}

    class FakeComputeClient:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def submit_action(self, envelope):
            captured["envelope"] = envelope
            return SimpleNamespace(job_id="job-1")

        async def poll_until_complete(self, job_id, **kwargs):
            captured["poll_job_id"] = job_id
            return SimpleNamespace(
                result=SimpleNamespace(value={"ssh": "ssh tenant@example"})
            )

        async def get_job_credentials(self, job_id):
            return [
                SimpleNamespace(
                    credential_kind="tenant",
                    value={"username": "tenant", "password": "secret"},
                )
            ]

    monkeypatch.setattr(orchestration, "ComputeProvisioningClient", FakeComputeClient)

    submitted = []
    async def record_submission(job_id):
        submitted.append(job_id)

    result = await orchestration.create_vm_and_wait_with_credentials(
        service_url="http://provisioning",
        admin_key="admin",
        timeout=10,
        poll_interval=0.01,
        vm_host="kvm1",
        allocation_id="allocation-1",
        deal_ref={"escrow_uid": "escrow-1", "listing_id": "listing-1"},
        parameters={"vm_target": "tenant-1", "ssh_pubkey": "ssh-ed25519 test"},
        on_job_submitted=record_submission,
    )

    envelope = captured["envelope"]
    assert envelope.contract_version == "1.0"
    assert envelope.allocation_id == "allocation-1"
    assert envelope.deal_ref["escrow_uid"] == "escrow-1"
    assert envelope.executor_kind == "vm"
    assert envelope.action_kind == "create"
    assert envelope.idempotency_key == "allocation-1:create"
    assert envelope.parameters["vm_target"] == "tenant-1"
    assert submitted == ["job-1"]
    assert result["authentication"]["tenant"]["username"] == "tenant"


@pytest.mark.asyncio
async def test_vm_lease_registration_uses_common_compute_model(monkeypatch):
    captured = {}

    class FakeComputeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def register_lease(self, registration):
            captured["registration"] = registration

    monkeypatch.setattr(
        fulfillment_service, "ComputeProvisioningClient", FakeComputeClient
    )
    monkeypatch.setattr(
        fulfillment_service,
        "settings",
        SimpleNamespace(
            provisioning=SimpleNamespace(service_url="http://provisioning"),
            admin_api_key="admin",
        ),
    )

    await fulfillment_service._register_vm_lease_with_settings(
        resource_id="resource-1",
        escrow_uid="escrow-1",
        vm_host="kvm1",
        vm_target="tenant-1",
        lease_start_utc="2026-07-13T12:00:00+00:00",
        lease_end_utc="2026-07-13 13:00",
        allocation_id="allocation-1",
    )

    registration = captured["registration"]
    assert registration.contract_version == "1.0"
    assert registration.allocation_id == "allocation-1"
    assert registration.deal_ref == {"escrow_uid": "escrow-1"}
    assert registration.executor_kind == "vm"
    assert registration.executor_target == "tenant-1"
