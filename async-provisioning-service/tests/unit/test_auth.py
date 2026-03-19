import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from async_provisioning_service.api import auth as auth_module


VALID_AGENT_ID = "eip155:84532:0x1111111111111111111111111111111111111111:7"


def test_validate_erc8004_agent_id_accepts_canonical_id():
    assert auth_module.validate_erc8004_agent_id(VALID_AGENT_ID) is True


def test_validate_erc8004_agent_id_rejects_invalid_id():
    assert auth_module.validate_erc8004_agent_id("not-an-agent-id") is False


def test_verify_agent_with_registry_fails_closed_when_registry_is_unreachable():
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(side_effect=RuntimeError("registry down"))

    with patch.object(auth_module.httpx, "AsyncClient", return_value=fake_client):
        result = asyncio.run(
            auth_module.verify_agent_with_registry(
                "http://registry.test",
                VALID_AGENT_ID,
                fail_open=False,
            )
        )

    assert result is False


def test_verify_agent_with_registry_can_fail_open_when_configured():
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(side_effect=RuntimeError("registry down"))

    with patch.object(auth_module.httpx, "AsyncClient", return_value=fake_client):
        result = asyncio.run(
            auth_module.verify_agent_with_registry(
                "http://registry.test",
                VALID_AGENT_ID,
                fail_open=True,
            )
        )

    assert result is True


def test_post_requires_x_agent_id_when_auth_enabled(client_factory):
    with client_factory(auth_enabled=True) as client:
        response = client.post("/api/v1/jobs", json={"vm_host": "ww1", "vm_action": "check"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-Agent-ID header"


def test_post_rejects_invalid_agent_id_when_auth_enabled(client_factory):
    with client_factory(auth_enabled=True) as client:
        response = client.post(
            "/api/v1/jobs",
            json={"vm_host": "ww1", "vm_action": "check"},
            headers={"X-Agent-ID": "invalid"},
        )

    assert response.status_code == 401
    assert "Invalid agent ID format" in response.json()["detail"]


def test_post_rejects_unregistered_agent_when_auth_enabled(client_factory):
    with patch.object(auth_module, "verify_agent_with_registry", AsyncMock(return_value=False)):
        with client_factory(auth_enabled=True) as client:
            response = client.post(
                "/api/v1/jobs",
                json={"vm_host": "ww1", "vm_action": "check"},
                headers={"X-Agent-ID": VALID_AGENT_ID},
            )

    assert response.status_code == 403
    assert response.json()["detail"] == "Agent not registered or unhealthy"
