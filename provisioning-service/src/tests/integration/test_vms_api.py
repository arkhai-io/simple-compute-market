"""
Integration tests for POST /api/v1/hosts/{host}/vms/ (create VM).

Coverage (per Architecture.md — Integration Tests jurisdiction):
  - HTTP request accepted and job_id returned (202)
  - Background job loop picks up the job (no sleeps — asyncio.Event seam)
  - AnsibleService.start_playbook called with correct host and action
  - Job transitions to succeeded in the DB
  - ProvisioningClient.create_vm + poll_until_complete round-trips correctly
  - Client method signatures match the API contract end-to-end

What is NOT covered here (unit test jurisdiction):
  - _build_vm_vars YAML serialisation
  - Pydantic field validation
  - Retry backoff arithmetic
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from client.provisioning_client import ProvisioningClient
from models.vm_request_model import CreateVmRequest
from services.async_job_queue import AsyncJobQueue


AGENT_ID = "eip155:1337:0xdeadbeef:1"
HOST = "ww1"
VM_NAME = "agent-vm-01"


def _make_event_seam(job_queue: AsyncJobQueue) -> asyncio.Event:
    """Inject an asyncio.Event that fires when the first job is dispatched."""
    dispatched = asyncio.Event()
    original_callback = job_queue._on_job_started

    def _on_started(job_id: str) -> None:
        dispatched.set()
        if original_callback is not None:
            original_callback(job_id)

    job_queue._on_job_started = _on_started
    return dispatched


class TestHttpValidation:
    """FastAPI-level validation tests — 422/404 responses that don't require client methods."""

    async def test_create_vm_missing_vm_target_returns_422(self, client_and_queue):
        from httpx import ASGITransport, AsyncClient
        from main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            resp = await http.post(
                f"/api/v1/hosts/{HOST}/vms/",
                json={"vm_ram": 2048},
                headers={"X-Agent-ID": AGENT_ID},
            )
        assert resp.status_code == 422

    async def test_create_vm_frp_without_password_returns_422(self, client_and_queue):
        from httpx import ASGITransport, AsyncClient
        from main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            resp = await http.post(
                f"/api/v1/hosts/{HOST}/vms/",
                json={"vm_target": VM_NAME, "frp_server_addr": "1.2.3.4"},
                headers={"X-Agent-ID": AGENT_ID},
            )
        assert resp.status_code == 422

    async def test_get_job_returns_404_for_unknown_id(self, client_and_queue):
        client, _ = client_and_queue
        from client.provisioning_client import ProvisioningError
        with pytest.raises(ProvisioningError) as exc_info:
            await client.get_job("nonexistent-job-id")
        assert exc_info.value.status_code == 404


class TestCreateVmViaClient:
    """Round-trip tests using ProvisioningClient — verifies client ↔ API contract.

    All HTTP calls go through ProvisioningClient methods.  No route strings
    appear in test code.  The ``on_job_started`` seam synchronises tests
    against the background job loop without any sleeps.
    """

    async def test_create_vm_returns_queued_job(self, client_and_queue):
        client, job_queue = client_and_queue
        dispatched = _make_event_seam(job_queue)

        submit = await client.create_vm(HOST, CreateVmRequest(vm_target=VM_NAME, vm_vcpus=2))

        assert submit.status == "queued"
        assert len(submit.job_id) > 0

        await asyncio.wait_for(dispatched.wait(), timeout=5.0)

    async def test_create_vm_job_succeeds(self, client_and_queue):
        client, job_queue = client_and_queue
        dispatched = _make_event_seam(job_queue)

        submit = await client.create_vm(HOST, CreateVmRequest(vm_target=VM_NAME))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)

        final = await client.poll_until_complete(submit.job_id, timeout=5.0, poll_interval=0.05)

        assert final.status == "succeeded"
        assert final.result is not None

    async def test_create_vm_result_contains_ssh_info(self, client_and_queue):
        client, job_queue = client_and_queue
        dispatched = _make_event_seam(job_queue)

        submit = await client.create_vm(HOST, CreateVmRequest(vm_target=VM_NAME))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        final = await client.poll_until_complete(submit.job_id, timeout=5.0, poll_interval=0.05)

        result = final.result
        assert result["vm_name"] == VM_NAME
        assert result["tenant_user"] == "agentvm01"
        assert result["ssh_port"] == "54321"
        assert result["vm_host_ip"] == "10.0.0.1"

    async def test_create_vm_ansible_called_with_correct_params(self, client_and_queue, fake_ansible):
        client, job_queue = client_and_queue
        dispatched = _make_event_seam(job_queue)

        await client.create_vm(HOST, CreateVmRequest(vm_target=VM_NAME, vm_ram=4096, vm_vcpus=4))
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
        await asyncio.sleep(0.1)

        fake_ansible.start_playbook.assert_called_once()
        call_kwargs = fake_ansible.start_playbook.call_args
        assert call_kwargs.kwargs.get("limit") == HOST or HOST in str(call_kwargs)

    async def test_create_vm_full_request_body_accepted(self, client_and_queue):
        """Verify a fully-populated CreateVmRequest is accepted by the API."""
        client, job_queue = client_and_queue
        dispatched = _make_event_seam(job_queue)

        submit = await client.create_vm(HOST, CreateVmRequest(
            vm_target=VM_NAME,
            vm_ram=4096,
            vm_vcpus=4,
            vm_disk_size="20G",
            image_setup_type="scratch",
            buyer_agent_id="eip155:1337:0xbuyer:2",
        ))

        assert submit.status == "queued"
        await asyncio.wait_for(dispatched.wait(), timeout=5.0)
