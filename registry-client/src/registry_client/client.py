"""HTTP clients for the Arkhai ERC-8004 registry REST API.

Two clients are provided with identical method signatures:

``RegistryClient``
    Async client backed by ``httpx.AsyncClient``.  Use in async application
    code and async test suites.

``SyncRegistryClient``
    Synchronous client backed by ``httpx.Client``.  Use in synchronous test
    suites and scripts.  Accepts the same ``transport=`` kwarg as the async
    client so it can be pointed at an in-process ASGI app during testing::

        transport = httpx.ASGITransport(app=app)
        client = SyncRegistryClient("http://test", transport=transport)
        health = client.get_health()   # no route strings in the caller

Both clients own their httpx session and must be closed when done.  Use as
context managers or call ``close()`` explicitly.

Both raise ``RegistryClientError`` on non-2xx responses.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from registry_client.auth import build_auth_headers, sign_eip191, RegistryClientError
from registry_client.models import (
    AgentListResponse,
    AgentSummary,
    HealthResponse,
    HeartbeatRequest,
    OrderListResponse,
    OrderRequest,
    OrderSummary,
    UpdateOrderRequest,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared logic — route construction, auth, response parsing
# ---------------------------------------------------------------------------


class _RegistryClientBase:
    """Route paths, auth helpers, and response parsers shared by both clients.

    Subclasses supply ``_get`` / ``_post`` / ``_delete`` that perform the
    actual HTTP call (async or sync).  This base class never touches the
    network directly.
    """

    def __init__(self, base_url: str, timeout: float) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Request builders — return (url, params, json, headers) tuples
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    @staticmethod
    def _agents_params(
        q: str | None,
        endpoint_type: str | None,
        trust_model: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q is not None:
            params["q"] = q
        if endpoint_type is not None:
            params["endpoint_type"] = endpoint_type
        if trust_model is not None:
            params["trust_model"] = trust_model
        return params

    @staticmethod
    def _orders_params(
        offer_resource_type: str | None,
        demand_resource_type: str | None,
        region: str | None,
        gpu_model: str | None,
        sla: float | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
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
        return params

    @staticmethod
    def _heartbeat_body(agent_id: str, private_key: str) -> tuple[dict, dict]:
        """Returns (json_body, headers) for a heartbeat POST."""
        timestamp = int(time.time())
        message = f"heartbeat:{agent_id}:{timestamp}"
        signature = sign_eip191(private_key, message)
        body = HeartbeatRequest(signature=signature, timestamp=timestamp)
        return body.to_dict(), {"Content-Type": "application/json"}

    @staticmethod
    def _publish_order_body(
        order: OrderRequest, agent_id: str, private_key: str
    ) -> tuple[dict, dict]:
        """Returns (json_body, headers) for a publish-order POST.

        The registry order route reads signature/timestamp from the request
        body (not from headers), so auth fields are embedded in the body dict.
        """
        auth = build_auth_headers(private_key, "create_order", agent_id)
        body = {
            **order.to_dict(),
            "signature": auth["X-Signature"],
            "timestamp": int(auth["X-Timestamp"]),
        }
        return body, {"Content-Type": "application/json"}

    @staticmethod
    def _delete_order_params(order_id: str, private_key: str) -> dict:
        """Returns query params for a delete-order DELETE."""
        timestamp = int(time.time())
        message = f"delete_order:{order_id}:{timestamp}"
        signature = sign_eip191(private_key, message)
        return {"signature": signature, "timestamp": timestamp}

    # ------------------------------------------------------------------
    # Response parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _raise_for_status(
        method: str, url: str, status: int, text: str, expected: tuple[int, ...]
    ) -> None:
        if status not in expected:
            raise RegistryClientError(method, url, status, text)

    @staticmethod
    def _parse_health(data: dict) -> HealthResponse:
        return HealthResponse.from_dict(data)

    @staticmethod
    def _parse_agent_list(data: Any) -> AgentListResponse:
        return AgentListResponse.from_raw(data)

    @staticmethod
    def _parse_agent(data: dict) -> AgentSummary:
        return AgentSummary.from_dict(data)

    @staticmethod
    def _parse_order_list(data: Any) -> OrderListResponse:
        return OrderListResponse.from_raw(data)

    @staticmethod
    def _parse_order(data: dict) -> OrderSummary:
        return OrderSummary.from_dict(data)


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class RegistryClient(_RegistryClientBase):
    """Async HTTP client for the Arkhai ERC-8004 registry REST API.

    Parameters
    ----------
    base_url:
        Base URL of the registry service (e.g. ``http://localhost:8080``).
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.AsyncBaseTransport`` to inject.  Primarily used in
        tests to supply ``httpx.ASGITransport(app=app)`` for in-process calls.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, timeout)
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        log.info("RegistryClient (async) initialised — base_url=%s", self._base)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "RegistryClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        headers: dict | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> Any:
        url = self._url(path)
        log.debug("%s %s params=%s", method, url, params)
        resp = await self._client.request(
            method, path, params=params, json=json, headers=headers
        )
        self._raise_for_status(method, url, resp.status_code, resp.text, expected)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ------------------------------------------------------------------
    # /health
    # ------------------------------------------------------------------

    async def get_health(self) -> HealthResponse:
        """GET /health → HealthResponse"""
        return self._parse_health(await self._request("GET", "/health"))

    # ------------------------------------------------------------------
    # /agents
    # ------------------------------------------------------------------

    async def list_agents(
        self,
        *,
        q: str | None = None,
        endpoint_type: str | None = None,
        trust_model: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> AgentListResponse:
        """GET /agents → AgentListResponse"""
        params = self._agents_params(q, endpoint_type, trust_model, limit, offset)
        return self._parse_agent_list(await self._request("GET", "/agents", params=params))

    async def get_agent(self, agent_id: str) -> AgentSummary:
        """GET /agents/{agent_id} → AgentSummary"""
        return self._parse_agent(await self._request("GET", f"/agents/{agent_id}"))

    async def search_agents(
        self, q: str, *, endpoint_type: str | None = None
    ) -> AgentListResponse:
        """GET /agents/search → AgentListResponse"""
        params: dict[str, Any] = {"q": q}
        if endpoint_type is not None:
            params["endpoint_type"] = endpoint_type
        return self._parse_agent_list(
            await self._request("GET", "/agents/search", params=params)
        )

    async def send_heartbeat(self, agent_id: str, private_key: str) -> dict:
        """POST /agents/{agent_id}/heartbeat with EIP-191 auth."""
        body, hdrs = self._heartbeat_body(agent_id, private_key)
        return await self._request(
            "POST", f"/agents/{agent_id}/heartbeat", json=body, headers=hdrs
        )

    # ------------------------------------------------------------------
    # /agents/{agent_id}/orders
    # ------------------------------------------------------------------

    async def publish_order(
        self, agent_id: str, order: OrderRequest, private_key: str
    ) -> dict:
        """POST /agents/{agent_id}/orders with EIP-191 auth headers."""
        body, hdrs = self._publish_order_body(order, agent_id, private_key)
        return await self._request(
            "POST", f"/agents/{agent_id}/orders",
            json=body, headers=hdrs, expected=(201,),
        )

    async def get_agent_orders(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> OrderListResponse:
        """GET /agents/{agent_id}/orders → OrderListResponse"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        return self._parse_order_list(
            await self._request("GET", f"/agents/{agent_id}/orders", params=params)
        )

    # ------------------------------------------------------------------
    # /orders
    # ------------------------------------------------------------------

    async def list_orders(
        self,
        *,
        offer_resource_type: Optional[str] = None,
        demand_resource_type: Optional[str] = None,
        region: Optional[str] = None,
        gpu_model: Optional[str] = None,
        sla: Optional[float] = None,
        status: Optional[str] = "open",
        limit: int = 50,
        offset: int = 0,
    ) -> OrderListResponse:
        """GET /orders → OrderListResponse"""
        params = self._orders_params(
            offer_resource_type, demand_resource_type, region,
            gpu_model, sla, status, limit, offset,
        )
        return self._parse_order_list(await self._request("GET", "/orders", params=params))

    async def get_order(self, order_id: str) -> OrderSummary:
        """GET /orders/{order_id} → OrderSummary"""
        data = await self._request("GET", f"/orders/{order_id}")
        # API wraps the order in {"order": {...}}
        return self._parse_order(data.get("order", data) if isinstance(data, dict) else data)

    async def update_order(self, order_id: str, request: UpdateOrderRequest) -> dict:
        """PUT /orders/{order_id} → updated order dict."""
        return await self._request("PUT", f"/orders/{order_id}", json=request.to_dict())

    async def delete_order(self, order_id: str, private_key: str) -> None:
        """DELETE /orders/{order_id} with EIP-191 auth query params."""
        params = self._delete_order_params(order_id, private_key)
        await self._request("DELETE", f"/orders/{order_id}", params=params, expected=(204,))


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------


class SyncRegistryClient(_RegistryClientBase):
    """Synchronous HTTP client for the Arkhai ERC-8004 registry REST API.

    Identical method signatures to ``RegistryClient`` but blocking.  Suitable
    for synchronous test suites and scripts.

    Parameters
    ----------
    base_url:
        Base URL of the registry service.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.BaseTransport`` to inject.  In registry-service
        integration tests this is ``httpx.ASGITransport(app=app)``, which
        drives FastAPI in-process without a network socket — no route strings
        in the test caller, full client method coverage.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, timeout)
        self._client = httpx.Client(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        log.info("SyncRegistryClient initialised — base_url=%s", self._base)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SyncRegistryClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        headers: dict | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> Any:
        url = self._url(path)
        log.debug("%s %s params=%s", method, url, params)
        resp = self._client.request(
            method, path, params=params, json=json, headers=headers
        )
        self._raise_for_status(method, url, resp.status_code, resp.text, expected)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ------------------------------------------------------------------
    # /health
    # ------------------------------------------------------------------

    def get_health(self) -> HealthResponse:
        """GET /health → HealthResponse"""
        return self._parse_health(self._request("GET", "/health"))

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
        params = self._agents_params(q, endpoint_type, trust_model, limit, offset)
        return self._parse_agent_list(self._request("GET", "/agents", params=params))

    def get_agent(self, agent_id: str) -> AgentSummary:
        """GET /agents/{agent_id} → AgentSummary"""
        return self._parse_agent(self._request("GET", f"/agents/{agent_id}"))

    def search_agents(self, q: str, *, endpoint_type: str | None = None) -> AgentListResponse:
        """GET /agents/search → AgentListResponse"""
        params: dict[str, Any] = {"q": q}
        if endpoint_type is not None:
            params["endpoint_type"] = endpoint_type
        return self._parse_agent_list(
            self._request("GET", "/agents/search", params=params)
        )

    def send_heartbeat(self, agent_id: str, private_key: str) -> dict:
        """POST /agents/{agent_id}/heartbeat with EIP-191 auth."""
        body, hdrs = self._heartbeat_body(agent_id, private_key)
        return self._request(
            "POST", f"/agents/{agent_id}/heartbeat", json=body, headers=hdrs
        )

    # ------------------------------------------------------------------
    # /agents/{agent_id}/orders
    # ------------------------------------------------------------------

    def publish_order(
        self, agent_id: str, order: OrderRequest, private_key: str
    ) -> dict:
        """POST /agents/{agent_id}/orders with EIP-191 auth headers."""
        body, hdrs = self._publish_order_body(order, agent_id, private_key)
        return self._request(
            "POST", f"/agents/{agent_id}/orders",
            json=body, headers=hdrs, expected=(201,),
        )

    def get_agent_orders(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> OrderListResponse:
        """GET /agents/{agent_id}/orders → OrderListResponse"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        return self._parse_order_list(
            self._request("GET", f"/agents/{agent_id}/orders", params=params)
        )

    # ------------------------------------------------------------------
    # /orders
    # ------------------------------------------------------------------

    def list_orders(
        self,
        *,
        offer_resource_type: Optional[str] = None,
        demand_resource_type: Optional[str] = None,
        region: Optional[str] = None,
        gpu_model: Optional[str] = None,
        sla: Optional[float] = None,
        status: Optional[str] = "open",
        limit: int = 50,
        offset: int = 0,
    ) -> OrderListResponse:
        """GET /orders → OrderListResponse"""
        params = self._orders_params(
            offer_resource_type, demand_resource_type, region,
            gpu_model, sla, status, limit, offset,
        )
        return self._parse_order_list(self._request("GET", "/orders", params=params))

    def get_order(self, order_id: str) -> OrderSummary:
        """GET /orders/{order_id} → OrderSummary"""
        data = self._request("GET", f"/orders/{order_id}")
        # API wraps the order in {"order": {...}}
        return self._parse_order(data.get("order", data) if isinstance(data, dict) else data)

    def update_order(self, order_id: str, request: UpdateOrderRequest) -> dict:
        """PUT /orders/{order_id} → updated order dict."""
        return self._request("PUT", f"/orders/{order_id}", json=request.to_dict())

    def delete_order(self, order_id: str, private_key: str) -> None:
        """DELETE /orders/{order_id} with EIP-191 auth query params."""
        params = self._delete_order_params(order_id, private_key)
        self._request("DELETE", f"/orders/{order_id}", params=params, expected=(204,))
