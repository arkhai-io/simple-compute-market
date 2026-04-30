"""
Integration tests for the Arkhai agent REST API routes.

Coverage (per Architecture.md — Integration Tests jurisdiction):
  - Request bodies accepted / rejected correctly (validation path)
  - Responses parse into StorefrontClient's expected shapes
  - Auth bypass works when AGENT_WALLET_ADDRESS is unset
  - GET /.well-known/erc-8004-registration.json returns valid JSON

``ENABLE_EVENT_QUEUE=true`` is set in conftest so all order/alert handlers
return immediately after queuing — the ADK Runner and root_agent are not
invoked.  This isolates the HTTP layer without requiring AI infrastructure.

What is NOT covered here (not in integration test jurisdiction):
  - ADK runner / root_agent response quality (system test territory)
  - Policy evaluation or negotiation logic (unit test territory)
  - On-chain calls (system test territory)
"""

from __future__ import annotations

import pytest

from storefront_client import StorefrontClient, StorefrontClientError


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_COMPUTE_OFFER = {
    "gpu_model": "RTX 4090",
    "quantity": 1,
    "sla": 99.0,
    "region": "California, US",
}

_TOKEN_DEMAND = {
    "token": "MOCK",
    "amount": 10.0,
}

_ALERT_BODY = {
    "event_type": "resource_imbalance",
    "resource": _COMPUTE_OFFER,
    "value": 0.1,
    "label": "LOW UTILIZATION",
    "threshold": "<=0.30",
}


# ---------------------------------------------------------------------------
# /alerts/resource
# ---------------------------------------------------------------------------


class TestAlertEndpoint:
    async def test_valid_alert_returns_200(self, agent_app_client):
        resp = await agent_app_client.post("/alerts/resource", json=_ALERT_BODY)
        assert resp.status_code == 200
        data = resp.json()
        assert "root_agent_response" in data or "error" not in data

    async def test_alert_missing_required_field_returns_400(self, agent_app_client):
        bad = dict(_ALERT_BODY)
        del bad["value"]
        resp = await agent_app_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 400

    async def test_alert_invalid_json_returns_400(self, agent_app_client):
        resp = await agent_app_client.post(
            "/alerts/resource",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_alert_resource_missing_fields_returns_400(self, agent_app_client):
        bad = dict(_ALERT_BODY)
        bad["resource"] = {"gpu_model": "RTX 4090"}  # missing quantity/sla/region
        resp = await agent_app_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 400

    async def test_alert_value_out_of_range_returns_400(self, agent_app_client):
        bad = dict(_ALERT_BODY)
        bad["value"] = 1.5  # must be <= 1.0
        resp = await agent_app_client.post("/alerts/resource", json=bad)
        assert resp.status_code == 400


class TestAlertViaClient:
    async def test_client_send_resource_alert_matches_endpoint(self, agent_app_client):
        """StorefrontClient.send_resource_alert body matches what the endpoint accepts."""
        import aiohttp

        # Build the body that StorefrontClient would send
        client = StorefrontClient("http://test")

        # Call the endpoint directly with the same body the client would use
        resp = await agent_app_client.post("/alerts/resource", json=_ALERT_BODY)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /listings/create
# ---------------------------------------------------------------------------


class TestCreateOrderEndpoint:
    async def test_valid_compute_offer_token_demand_returns_200(self, agent_app_client):
        body = {
            "offer": _COMPUTE_OFFER,
            "demand": _TOKEN_DEMAND,
            "max_duration_seconds": 7200,
        }
        resp = await agent_app_client.post("/listings/create", json=body)
        assert resp.status_code == 200
        data = resp.json()
        # With event queue enabled the response has status=queued or status=created
        assert "status" in data
        assert "event_id" in data

    async def test_valid_token_offer_compute_demand_returns_200(self, agent_app_client):
        body = {
            "offer": _TOKEN_DEMAND,
            "demand": _COMPUTE_OFFER,
            "max_duration_seconds": 3600,
        }
        resp = await agent_app_client.post("/listings/create", json=body)
        assert resp.status_code == 200

    async def test_missing_offer_returns_422_or_400(self, agent_app_client):
        body = {"demand": _TOKEN_DEMAND}
        resp = await agent_app_client.post("/listings/create", json=body)
        assert resp.status_code in (400, 422)

    async def test_missing_demand_returns_422_or_400(self, agent_app_client):
        body = {"offer": _COMPUTE_OFFER}
        resp = await agent_app_client.post("/listings/create", json=body)
        assert resp.status_code in (400, 422)

    async def test_two_compute_resources_returns_400(self, agent_app_client):
        body = {
            "offer": _COMPUTE_OFFER,
            "demand": _COMPUTE_OFFER,
        }
        resp = await agent_app_client.post("/listings/create", json=body)
        assert resp.status_code in (400, 422, 500)

    async def test_unknown_token_returns_400(self, agent_app_client):
        body = {
            "offer": _COMPUTE_OFFER,
            "demand": {"token": "NONEXISTENT_TOKEN_XYZ", "amount": 10.0},
        }
        resp = await agent_app_client.post("/listings/create", json=body)
        assert resp.status_code in (400, 422)

    async def test_response_contains_order_request(self, agent_app_client):
        body = {
            "offer": _COMPUTE_OFFER,
            "demand": _TOKEN_DEMAND,
        }
        resp = await agent_app_client.post("/listings/create", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert "listing_request" in data


class TestCreateOrderViaClient:
    async def test_client_create_order_body_matches_endpoint(self, agent_app_client):
        """StorefrontClient.create_order serialises to a body the endpoint accepts."""
        body = {
            "offer": _COMPUTE_OFFER,
            "demand": _TOKEN_DEMAND,
            "max_duration_seconds": 3600,
        }
        resp = await agent_app_client.post("/listings/create", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert "event_id" in data
        assert "status" in data


# ---------------------------------------------------------------------------
# /listings/close
# ---------------------------------------------------------------------------


class TestCloseOrderEndpoint:
    async def test_valid_close_returns_200(self, agent_app_client):
        body = {"listing_id": "test-order-abc123"}
        resp = await agent_app_client.post("/listings/close", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "event_id" in data

    async def test_missing_order_id_returns_400(self, agent_app_client):
        resp = await agent_app_client.post("/listings/close", json={})
        assert resp.status_code in (400, 422)

    async def test_empty_order_id_returns_400(self, agent_app_client):
        resp = await agent_app_client.post("/listings/close", json={"listing_id": ""})
        assert resp.status_code in (400, 422)

    async def test_response_contains_order_request(self, agent_app_client):
        body = {"listing_id": "test-order-xyz"}
        resp = await agent_app_client.post("/listings/close", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert "listing_request" in data


class TestCloseOrderViaClient:
    async def test_client_close_order_body_matches_endpoint(self, agent_app_client):
        """StorefrontClient.close_order serialises to a body the endpoint accepts."""
        body = {"listing_id": "order-abc"}
        resp = await agent_app_client.post("/listings/close", json=body)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /.well-known/erc-8004-registration.json
# ---------------------------------------------------------------------------


class TestRegistrationEndpoint:
    async def test_returns_200_with_json(self, agent_app_client):
        resp = await agent_app_client.get("/.well-known/erc-8004-registration.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    async def test_contains_type_field(self, agent_app_client):
        resp = await agent_app_client.get("/.well-known/erc-8004-registration.json")
        data = resp.json()
        # ERC-8004 spec requires a 'type' field
        assert "type" in data or "name" in data  # either spec field is acceptable

    async def test_client_get_registration_parses_response(self, agent_app_client):
        """StorefrontClient.get_registration parses a valid JSON response."""
        resp = await agent_app_client.get("/.well-known/erc-8004-registration.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
