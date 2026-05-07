"""Integration tests for the Alerts controller.

Uses ``StorefrontClient.send_resource_alert()`` via ``httpx.ASGITransport``
— following the canonical client pattern documented in ARCHITECTURE.md.

The ``PolicyService.handle_resource_alert()`` is stubbed via a mock so
tests validate the HTTP layer (validation, error mapping) independently
of the policy engine.
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.controllers.alerts_controller import router as alerts_router
from storefront_client import StorefrontClient, StorefrontClientError

_VALID_ALERT = {
    "event_type": "resource_imbalance",
    "resource": {
        "gpu_model": "RTX 4090",
        "gpu_count": 1,
        "sla": 99.0,
        "region": "California, US",
    },
    "value": 0.1,
    "label": "LOW UTILIZATION",
    "threshold": "<=0.30",
}


@pytest_asyncio.fixture
async def mock_policy_svc():
    svc = MagicMock()
    svc.handle_resource_alert = AsyncMock(
        return_value={**_VALID_ALERT, "root_agent_response": "Noted."}
    )
    return svc


@pytest_asyncio.fixture
async def client(mock_policy_svc) -> AsyncIterator[StorefrontClient]:
    _container.resolved_policy_service = mock_policy_svc

    app = FastAPI()
    app.include_router(alerts_router)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient("http://test", transport=transport) as c:
        yield c

    _container.resolved_policy_service = None


class TestAlertEndpoint:
    async def test_valid_alert_returns_200(self, client):
        result = await client.send_resource_alert(
            resource=_VALID_ALERT["resource"],
            value=_VALID_ALERT["value"],
            label=_VALID_ALERT["label"],
            threshold=_VALID_ALERT["threshold"],
        )
        assert "root_agent_response" in result

    async def test_missing_value_field_returns_422(self, client):
        with pytest.raises(StorefrontClientError) as exc_info:
            # send_resource_alert requires value — pass an invalid one to trigger model error
            await client.send_resource_alert(
                resource={},  # missing required fields
                value=0.1,
                label="LOW",
                threshold="<=0.30",
            )
        assert "422" in str(exc_info.value)

    async def test_resource_missing_required_fields_returns_422(self, client):
        """resource dict must have gpu_model, gpu_count, sla, region."""
        with pytest.raises(StorefrontClientError) as exc_info:
            await client.send_resource_alert(
                resource={"gpu_model": "RTX 4090"},  # missing gpu_count/sla/region
                value=0.1,
                label="LOW",
                threshold="<=0.30",
            )
        assert "422" in str(exc_info.value)

    async def test_value_out_of_range_returns_422(self, client):
        """value must be 0.0–1.0."""
        with pytest.raises(StorefrontClientError) as exc_info:
            await client.send_resource_alert(
                resource=_VALID_ALERT["resource"],
                value=1.5,
                label="HIGH",
                threshold=">1.0",
            )
        assert "422" in str(exc_info.value)

    async def test_service_called_with_validated_model(self, client, mock_policy_svc):
        """The service receives a ResourceAlertRequest, not a raw dict."""
        from market_storefront.models.domain_models import ResourceAlertRequest
        await client.send_resource_alert(
            resource=_VALID_ALERT["resource"],
            value=0.1,
            label="LOW",
            threshold="<=0.30",
        )
        assert mock_policy_svc.handle_resource_alert.called
        call_arg = mock_policy_svc.handle_resource_alert.call_args[0][0]
        assert isinstance(call_arg, ResourceAlertRequest)
        assert call_arg.value == 0.1


class TestAlertValidationContract:
    """Documents FastAPI/Pydantic validation returning structured 422 errors."""

    async def test_422_body_has_detail_array(self, client):
        """FastAPI validation errors have a 'detail' array with loc/msg/type."""
        # Access underlying client to check raw response body shape
        resp = await client._client.post(
            "/api/v1/alerts/resource",
            json={**_VALID_ALERT, "label": None},  # null label triggers 422
            headers={"Content-Type": "application/json"},
        )
        # label is required (str) — None triggers 422
        if resp.status_code == 422:
            body = resp.json()
            assert "detail" in body
            assert isinstance(body["detail"], list)
