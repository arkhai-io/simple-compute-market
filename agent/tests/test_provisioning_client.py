"""
Integration tests for provisioning client.

Tests the agent's HTTP client for the async provisioning service.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch

from app.utils.provisioning_client import (
    provision_machine_async,
    format_connection_info,
    ProvisioningError,
    ProvisioningJobError,
    ProvisioningTimeoutError,
)


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.AsyncClient."""
    with patch("app.utils.provisioning_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client_class.return_value.__aexit__.return_value = AsyncMock()
        yield mock_client


@pytest.mark.asyncio
async def test_provision_machine_success(mock_httpx_client):
    """Test successful provisioning flow."""
    # Mock POST /provision response
    mock_submit_response = Mock()
    mock_submit_response.status_code = 202
    mock_submit_response.json.return_value = {
        "job_id": "test-job-123",
        "status": "queued",
    }
    mock_submit_response.raise_for_status = Mock()

    # Mock GET /provision/{job_id} responses (queued -> running -> succeeded)
    mock_status_queued = Mock()
    mock_status_queued.status_code = 200
    mock_status_queued.json.return_value = {
        "job_id": "test-job-123",
        "status": "queued",
        "params": {},
        "result": None,
        "error": None,
    }
    mock_status_queued.raise_for_status = Mock()

    mock_status_running = Mock()
    mock_status_running.status_code = 200
    mock_status_running.json.return_value = {
        "job_id": "test-job-123",
        "status": "running",
        "params": {},
        "result": None,
        "error": None,
    }
    mock_status_running.raise_for_status = Mock()

    mock_status_succeeded = Mock()
    mock_status_succeeded.status_code = 200
    mock_status_succeeded.json.return_value = {
        "job_id": "test-job-123",
        "status": "succeeded",
        "params": {},
        "result": {
            "external_port": "2222",
            "tenant_user": "tenant1",
            "vm_host_ip": "192.168.1.100",
            "ssh_command": "ssh -i <your_private_key> -p 2222 tenant1@192.168.1.100",
        },
        "error": None,
    }
    mock_status_succeeded.raise_for_status = Mock()

    # Configure mock to return different responses for different calls
    mock_httpx_client.post = AsyncMock(return_value=mock_submit_response)
    mock_httpx_client.get = AsyncMock(
        side_effect=[
            mock_status_queued,
            mock_status_running,
            mock_status_succeeded,
        ]
    )

    # Test provisioning
    result = await provision_machine_async(
        provisioning_service_url="http://localhost:8081",
        ssh_public_key="ssh-ed25519 AAAA...",
        timeout=60,
        poll_interval=1,
    )

    # Verify result
    assert result["external_port"] == "2222"
    assert result["tenant_user"] == "tenant1"
    assert result["vm_host_ip"] == "192.168.1.100"
    assert result["ssh_command"] == "ssh -i <your_private_key> -p 2222 tenant1@192.168.1.100"

    # Verify API calls
    mock_httpx_client.post.assert_called_once()
    assert mock_httpx_client.get.call_count >= 2  # At least queued and succeeded


@pytest.mark.asyncio
async def test_provision_machine_job_failure(mock_httpx_client):
    """Test provisioning job failure."""
    # Mock POST /provision response
    mock_submit_response = Mock()
    mock_submit_response.status_code = 202
    mock_submit_response.json.return_value = {
        "job_id": "test-job-456",
        "status": "queued",
    }
    mock_submit_response.raise_for_status = Mock()

    # Mock GET /provision/{job_id} response (failed)
    mock_status_failed = Mock()
    mock_status_failed.status_code = 200
    mock_status_failed.json.return_value = {
        "job_id": "test-job-456",
        "status": "failed",
        "params": {},
        "result": None,
        "error": "Ansible playbook failed",
    }
    mock_status_failed.raise_for_status = Mock()

    # Mock GET /provision/{job_id}/logs response
    mock_logs_response = Mock()
    mock_logs_response.status_code = 200
    mock_logs_response.json.return_value = {
        "job_id": "test-job-456",
        "status": "failed",
        "logs": "TASK [Create VM] failed...",
    }

    mock_httpx_client.post = AsyncMock(return_value=mock_submit_response)
    mock_httpx_client.get = AsyncMock(
        side_effect=[
            mock_status_failed,  # First GET (status check)
            mock_logs_response,  # Second GET (logs)
        ]
    )

    # Test provisioning (should raise exception)
    with pytest.raises(ProvisioningJobError, match="Ansible playbook failed"):
        await provision_machine_async(
            provisioning_service_url="http://localhost:8081",
            ssh_public_key="ssh-ed25519 AAAA...",
            timeout=60,
            poll_interval=1,
        )


@pytest.mark.asyncio
async def test_provision_machine_timeout(mock_httpx_client):
    """Test provisioning timeout."""
    # Mock POST /provision response
    mock_submit_response = Mock()
    mock_submit_response.status_code = 202
    mock_submit_response.json.return_value = {
        "job_id": "test-job-789",
        "status": "queued",
    }
    mock_submit_response.raise_for_status = Mock()

    # Mock GET /provision/{job_id} response (always running)
    mock_status_running = Mock()
    mock_status_running.status_code = 200
    mock_status_running.json.return_value = {
        "job_id": "test-job-789",
        "status": "running",
        "params": {},
        "result": None,
        "error": None,
    }
    mock_status_running.raise_for_status = Mock()

    mock_httpx_client.post = AsyncMock(return_value=mock_submit_response)
    mock_httpx_client.get = AsyncMock(return_value=mock_status_running)

    # Test provisioning with short timeout (should raise timeout exception)
    with pytest.raises(ProvisioningTimeoutError, match="timed out"):
        await provision_machine_async(
            provisioning_service_url="http://localhost:8081",
            ssh_public_key="ssh-ed25519 AAAA...",
            timeout=2,  # 2 second timeout
            poll_interval=1,
        )


def test_format_connection_info_with_ssh_command():
    """Test formatting connection info from result with ssh_command."""
    result = {
        "external_port": "2222",
        "tenant_user": "tenant1",
        "vm_host_ip": "192.168.1.100",
        "ssh_command": "ssh -i <your_private_key> -p 2222 tenant1@192.168.1.100",
    }

    connection_info = format_connection_info(result)
    assert connection_info == "ssh -i <your_private_key> -p 2222 tenant1@192.168.1.100"


def test_format_connection_info_without_ssh_command():
    """Test formatting connection info from result without ssh_command."""
    result = {
        "external_port": "2222",
        "tenant_user": "tenant1",
        "vm_host_ip": "192.168.1.100",
    }

    connection_info = format_connection_info(result)
    assert connection_info == "ssh tenant1@192.168.1.100 -p 2222"


def test_format_connection_info_incomplete():
    """Test formatting connection info with incomplete result."""
    result = {
        "external_port": "2222",
    }

    connection_info = format_connection_info(result)
    # Should return raw result as string
    assert "2222" in connection_info
