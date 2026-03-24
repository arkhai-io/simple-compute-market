from __future__ import annotations

from typing import Any

import httpx
import logging
import time

from src.models.registry import (
    AgentListResponse,
    AgentSummary,
    HealthResponse,
    HeartbeatRequest,
    OrderListResponse,
    OrderRequest,
    OrderSummary,
)

from src.eip191_http_client import sign_eip191, build_auth_headers, ApiError

log = logging.getLogger(__name__)

class RegistryClient:
    """
    Synchronous client for the Registry REST API.

    Instantiate once per test session (session-scoped fixture in conftest).
    All methods raise ``ApiError`` on non-2xx responses.
    """

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        log.info("RegistryClient initialised — base_url=%s", self._base_url)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        headers: dict | None = None,
        expected_statuses: tuple[int, ...] = (200, 201),
    ) -> httpx.Response:
        log.debug("%s %s params=%s", method, path, params)
        resp = self._http.request(method, path, params=params, json=json, headers=headers)
        if resp.status_code not in expected_statuses:
            raise ApiError(method, f"{self._base_url}{path}", resp.status_code, resp.text)
        return resp

    # ------------------------------------------------------------------
    # /health
    # ------------------------------------------------------------------

    def get_health(self) -> HealthResponse:
        """GET /health → HealthResponse"""
        resp = self._request("GET", "/health")
        return HealthResponse.from_dict(resp.json())

    # ------------------------------------------------------------------
    # /agents
    # ------------------------------------------------------------------

    def list_agents(
        self,
        *,
        q: str | None = None,
        endpoint_type: str | None = None,
        trust_model: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> AgentListResponse:
        """GET /agents → AgentListResponse"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q is not None:
            params["q"] = q
        if endpoint_type is not None:
            params["endpoint_type"] = endpoint_type
        if trust_model is not None:
            params["trust_model"] = trust_model
        resp = self._request("GET", "/agents", params=params)
        return AgentListResponse.from_raw(resp.json())

    def get_agent(self, agent_id: str) -> AgentSummary:
        """GET /agents/{agent_id} → AgentSummary"""
        resp = self._request("GET", f"/agents/{agent_id}")
        return AgentSummary.from_dict(resp.json())

    def search_agents(
        self,
        q: str,
        *,
        endpoint_type: str | None = None,
    ) -> AgentListResponse:
        """GET /agents/search → AgentListResponse"""
        params: dict[str, Any] = {"q": q}
        if endpoint_type is not None:
            params["endpoint_type"] = endpoint_type
        resp = self._request("GET", "/agents/search", params=params)
        return AgentListResponse.from_raw(resp.json())

    def send_heartbeat(
        self,
        agent_id: str,
        private_key: str,
    ) -> httpx.Response:
        """POST /agents/{agent_id}/heartbeat with EIP-191 auth."""
        timestamp = int(time.time())
        message = f"heartbeat:{agent_id}:{timestamp}"
        signature = sign_eip191(private_key, message)
        body = HeartbeatRequest(signature=signature, timestamp=timestamp)
        return self._request(
            "POST",
            f"/agents/{agent_id}/heartbeat",
            json=body.to_dict(),
            headers={"Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------
    # /agents/{agent_id}/orders
    # ------------------------------------------------------------------

    def publish_order(
        self,
        agent_id: str,
        order: OrderRequest,
        private_key: str,
    ) -> httpx.Response:
        """POST /agents/{agent_id}/orders with auth headers."""
        headers = build_auth_headers(private_key, "publish_order", agent_id)
        return self._request(
            "POST",
            f"/agents/{agent_id}/orders",
            json=order.to_dict(),
            headers=headers,
            expected_statuses=(201,),
        )

    def get_agent_orders(
        self,
        agent_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> OrderListResponse:
        """GET /agents/{agent_id}/orders → OrderListResponse"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        resp = self._request("GET", f"/agents/{agent_id}/orders", params=params)
        return OrderListResponse.from_raw(resp.json())

    # ------------------------------------------------------------------
    # /orders
    # ------------------------------------------------------------------

    def list_orders(
        self,
        *,
        offer_resource_type: str | None = None,
        demand_resource_type: str | None = None,
        region: str | None = None,
        gpu_model: str | None = None,
        sla: float | None = None,
        status: str | None = "open",
        limit: int = 50,
        offset: int = 0,
    ) -> OrderListResponse:
        """GET /orders → OrderListResponse"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        for key, val in [
            ("offer_resource_type", offer_resource_type),
            ("demand_resource_type", demand_resource_type),
            ("region", region),
            ("gpu_model", gpu_model),
            ("sla", sla),
            ("status", status),
        ]:
            if val is not None:
                params[key] = val
        resp = self._request("GET", "/orders", params=params)
        return OrderListResponse.from_raw(resp.json())

    def get_order(self, order_id: str) -> OrderSummary:
        """GET /orders/{order_id} → OrderSummary"""
        resp = self._request("GET", f"/orders/{order_id}")
        return OrderSummary.from_dict(resp.json())

    def delete_order(
        self,
        order_id: str,
        private_key: str,
    ) -> httpx.Response:
        """DELETE /orders/{order_id} with EIP-191 auth query params."""
        timestamp = int(time.time())
        message = f"delete_order:{order_id}:{timestamp}"
        signature = sign_eip191(private_key, message)
        return self._request(
            "DELETE",
            f"/orders/{order_id}",
            params={"signature": signature, "timestamp": timestamp},
            expected_statuses=(204,),
        )
