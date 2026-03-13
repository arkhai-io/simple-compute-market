"""Unit tests for service.clients.provisioning (HTTP client)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_response(status: int, json_data: dict):
    """Helper to make a mock aiohttp response."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _make_cm(resp):
    """Return a sync context manager that yields resp from __aenter__."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_provision_machine_happy_path():
    """Test queued -> running -> succeeded path."""
    from service.clients.provisioning import provision_machine_async

    submit_resp = _make_mock_response(201, {"job_id": "job123"})
    poll_resp_1 = _make_mock_response(200, {"status": "queued"})
    poll_resp_2 = _make_mock_response(200, {"status": "running"})
    poll_resp_3 = _make_mock_response(200, {"status": "succeeded", "result": {"ssh_command": "ssh user@host"}})

    responses = [submit_resp, poll_resp_1, poll_resp_2, poll_resp_3]
    call_count = [0]

    def mock_request(*args, **kwargs):
        resp = responses[call_count[0]]
        call_count[0] += 1
        return _make_cm(resp)

    with patch("aiohttp.ClientSession") as mock_session_cls:
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(side_effect=mock_request)
        session.get = MagicMock(side_effect=mock_request)
        mock_session_cls.return_value = session

        result = await provision_machine_async(
            "http://provisioner:8085",
            {"vm_host": "ww1", "ssh_pubkey": "ssh-ed25519 AAAA"},
            timeout=60,
            poll_interval=0,
        )
    assert result["ssh_command"] == "ssh user@host"


@pytest.mark.asyncio
async def test_provision_machine_job_failed():
    """Test that failed status raises ProvisioningJobError."""
    from service.clients.provisioning import provision_machine_async, ProvisioningJobError

    submit_resp = _make_mock_response(201, {"job_id": "job456"})
    poll_resp = _make_mock_response(200, {"status": "failed", "error": "ansible error"})

    responses = [submit_resp, poll_resp]
    call_count = [0]

    def mock_request(*args, **kwargs):
        resp = responses[call_count[0]]
        call_count[0] += 1
        return _make_cm(resp)

    with patch("aiohttp.ClientSession") as mock_session_cls:
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(side_effect=mock_request)
        session.get = MagicMock(side_effect=mock_request)
        mock_session_cls.return_value = session

        with pytest.raises(ProvisioningJobError, match="ansible error"):
            await provision_machine_async(
                "http://provisioner:8085",
                {},
                timeout=60,
                poll_interval=0,
            )


@pytest.mark.asyncio
async def test_provision_machine_x_agent_id_header():
    """Test that X-Agent-ID header is sent when agent_id is provided."""
    from service.clients.provisioning import provision_machine_async

    captured_headers = {}

    def capture_post(url, json=None, headers=None):
        captured_headers.update(headers or {})
        return _make_cm(_make_mock_response(201, {"job_id": "job789"}))

    def capture_get(url, headers=None):
        return _make_cm(_make_mock_response(200, {"status": "succeeded", "result": {}}))

    with patch("aiohttp.ClientSession") as mock_session_cls:
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(side_effect=capture_post)
        session.get = MagicMock(side_effect=capture_get)
        mock_session_cls.return_value = session

        await provision_machine_async(
            "http://provisioner:8085",
            {},
            timeout=60,
            poll_interval=0,
            agent_id="eip155:1:0xabcd:42",
        )
    assert captured_headers.get("X-Agent-ID") == "eip155:1:0xabcd:42"
