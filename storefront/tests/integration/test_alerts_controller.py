"""Integration tests for the Alerts controller.

POST /alerts/resource — resource imbalance alert ingestion.

Key testability improvement over the original agent.py handler:
- ResourceAlertRequest validation is now handled by FastAPI/Pydantic
  and returns structured 422 errors automatically.
- Tests can assert directly on the 422 body schema instead of the
  custom 400 error serialization used in the original handler.
- The StorefrontService.handle_resource_alert() is called for valid
  requests; the policy pipeline is tested through StorefrontService
  unit tests.

Integration tests here verify only the HTTP layer:
- Required fields are enforced (422 on missing)
- Valid request reaches the service and returns 200
- Invalid JSON returns the appropriate error response
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
async def mock_svc():
    """Stub StorefrontService that returns a canned alert response."""
    svc = MagicMock()
    svc.handle_resource_alert = AsyncMock(
        return_value={**_VALID_ALERT, "root_agent_response": "Noted."}
    )
    return svc


@pytest_asyncio.fixture
async def http_client(mock_svc) -> AsyncIterator[httpx.AsyncClient]:
    _container.resolved_policy_pipeline_service = mock_svc

    app = FastAPI()
    app.include_router(alerts_router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    _container.resolved_policy_pipeline_service = None


class TestAlertEndpoint:
    async def test_valid_alert_returns_200(self, http_client):
        resp = await http_client.post("/alerts/resource", json=_VALID_ALERT)
        assert resp.status_code == 200
        body = resp.json()
        assert "root_agent_response" in body

    async def test_missing_value_field_returns_422(self, http_client):
        bad = dict(_VALID_ALERT)
        del bad["value"]
        resp = await http_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 422

    async def test_missing_resource_field_returns_422(self, http_client):
        bad = dict(_VALID_ALERT)
        del bad["resource"]
        resp = await http_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 422

    async def test_resource_missing_required_fields_returns_422(self, http_client):
        """resource dict must have gpu_model, gpu_count, sla, region."""
        bad = dict(_VALID_ALERT)
        bad["resource"] = {"gpu_model": "RTX 4090"}  # missing gpu_count/sla/region
        resp = await http_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 422

    async def test_wrong_event_type_returns_422(self, http_client):
        bad = dict(_VALID_ALERT)
        bad["event_type"] = "wrong_type"
        resp = await http_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 422

    async def test_value_out_of_range_returns_422(self, http_client):
        """value must be 0.0–1.0 per ResourceAlertRequest validator."""
        bad = dict(_VALID_ALERT)
        bad["value"] = 1.5
        resp = await http_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 422

    async def test_invalid_json_returns_422(self, http_client):
        resp = await http_client.post(
            "/alerts/resource",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    async def test_service_called_with_validated_model(self, http_client, mock_svc):
        """The service receives a ResourceAlertRequest, not a raw dict."""
        from market_storefront.models.domain_models import ResourceAlertRequest
        await http_client.post("/alerts/resource", json=_VALID_ALERT)
        assert mock_svc.handle_resource_alert.called
        call_arg = mock_svc.handle_resource_alert.call_args[0][0]
        assert isinstance(call_arg, ResourceAlertRequest)
        assert call_arg.value == 0.1


class TestAlertEndpointImprovement:
    """Tests that document the improvement over the original agent.py handler.

    The original handler returned 400 with a custom error format.
    FastAPI/Pydantic returns structured 422 with a standard error body.
    These tests confirm the new behaviour is consistent.
    """

    async def test_422_body_has_detail_array(self, http_client):
        """FastAPI validation errors have a 'detail' array with loc/msg/type."""
        bad = dict(_VALID_ALERT)
        del bad["label"]
        resp = await http_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 422
        body = resp.json()
        assert "detail" in body
        assert isinstance(body["detail"], list)
        # At least one error references 'label'
        locs = [str(e.get("loc", "")) for e in body["detail"]]
        assert any("label" in loc for loc in locs)
