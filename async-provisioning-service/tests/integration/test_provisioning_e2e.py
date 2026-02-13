import os
import time

import httpx
import pytest


E2E_ENABLED = os.getenv("E2E_PROVISIONING", "0") == "1"


@pytest.mark.skipif(not E2E_ENABLED, reason="E2E provisioning disabled")
def test_provisioning_e2e():
    base_url = os.getenv("PROVISIONING_BASE_URL", "http://localhost:8081")
    ssh_pubkey = os.getenv("PROVISIONING_TEST_SSH_PUBKEY")
    if not ssh_pubkey:
        pytest.skip("Missing PROVISIONING_TEST_SSH_PUBKEY")

    request_payload = {
        "ssh_pubkey": ssh_pubkey,
        "vm_host": os.getenv("PROVISIONING_VM_HOST", "vm1"),
    }

    with httpx.Client(timeout=30) as client:
        response = client.post(f"{base_url}/provision", json=request_payload)
        response.raise_for_status()
        job_id = response.json()["job_id"]

        status = "queued"
        deadline = time.time() + 3600
        while time.time() < deadline and status in {"queued", "running"}:
            status_response = client.get(f"{base_url}/provision/{job_id}")
            status_response.raise_for_status()
            status = status_response.json()["status"]
            if status in {"queued", "running"}:
                time.sleep(15)

        assert status == "succeeded"

        logs_response = client.get(f"{base_url}/provision/{job_id}/logs")
        logs_response.raise_for_status()
        assert logs_response.json().get("logs")
