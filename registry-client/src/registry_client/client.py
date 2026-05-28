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
    AgentIndexedResponse,
    AgentListResponse,
    AgentSummary,
    FilterSpecResponse,
    HealthResponse,
    HeartbeatRequest,
    ListingListResponse,
    ListingRequest,
    ListingSummary,
    SystemConfigResponse,
    SystemSyncResponse,
    SystemStatsResponse,
    UpdateListingRequest,
    ValidatePublishRequest,
    ValidatePublishResponse,
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
    def _listings_params(
        *,
        status: str | None,
        limit: int,
        offset: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        """Build query params for GET /listings.

        ``filters`` is an opaque dict keyed on the registry's filter-spec
        names — the client doesn't enumerate them.  Buyers can fetch
        ``/filter-spec`` to discover what's available.  Bool values are
        stringified ("true"/"false") since FastAPI parses query bools from
        those literals.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        for key, val in filters.items():
            if val is None:
                continue
            params[key] = str(val).lower() if isinstance(val, bool) else val
        return params

    @staticmethod
    def _if_match_headers(etag: str | None) -> dict[str, str] | None:
        if etag is None:
            return None
        normalized = etag if etag.startswith('"') else f'"{etag}"'
        return {"If-Match": normalized}

    @staticmethod
    def _heartbeat_body(agent_id: str, private_key: str) -> tuple[dict, dict]:
        """Returns (json_body, headers) for a heartbeat POST."""
        timestamp = int(time.time())
        message = f"heartbeat:{agent_id}:{timestamp}"
        signature = sign_eip191(private_key, message)
        body = HeartbeatRequest(signature=signature, timestamp=timestamp)
        return body.to_dict(), {"Content-Type": "application/json"}

    @staticmethod
    def _publish_listing_body(
        listing: ListingRequest, agent_id: str, private_key: str
    ) -> tuple[dict, dict]:
        """Returns (json_body, headers) for a publish-listing POST.

        The registry listing route reads signature/timestamp from the
        request body (not from headers), so auth fields are embedded in
        the body dict.
        """
        auth = build_auth_headers(private_key, "create_listing", agent_id)
        body = {
            **listing.to_dict(),
            "signature": auth["X-Signature"],
            "timestamp": int(auth["X-Timestamp"]),
        }
        return body, {"Content-Type": "application/json"}

    @staticmethod
    def _delete_listing_params(listing_id: str, private_key: str) -> dict:
        """Returns query params for a delete-listing DELETE."""
        timestamp = int(time.time())
        message = f"delete_listing:{listing_id}:{timestamp}"
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
    def _parse_listing_list(data: Any) -> ListingListResponse:
        return ListingListResponse.from_raw(data)

    @staticmethod
    def _parse_listing(data: dict) -> ListingSummary:
        return ListingSummary.from_dict(data)

    @staticmethod
    def _parse_system_config(data: dict) -> SystemConfigResponse:
        return SystemConfigResponse.from_dict(data)

    @staticmethod
    def _parse_system_sync(data: dict) -> SystemSyncResponse:
        return SystemSyncResponse.from_dict(data)

    @staticmethod
    def _parse_system_stats(data: dict) -> SystemStatsResponse:
        return SystemStatsResponse.from_dict(data)

    @staticmethod
    def _parse_agent_indexed(data: dict) -> AgentIndexedResponse:
        return AgentIndexedResponse.from_dict(data)


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
        api_key: str | None = None,
    ) -> None:
        """``api_key`` — optional bearer token sent on every request as
        ``Authorization: Bearer <key>``. Private registries that gate
        access behind an API key set this; public registries leave it
        ``None``. The key is layered on top of any per-call EIP-191
        signing (publish/delete/heartbeat) — both can be required in
        parallel by stricter deployments."""
        super().__init__(base_url, timeout)
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
            headers=headers,
        )
        log.info(
            "RegistryClient (async) initialised — base_url=%s api_key=%s",
            self._base, "set" if api_key else "none",
        )

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

    async def get_system_config(self) -> SystemConfigResponse:
        """GET /api/v1/system/config → SystemConfigResponse"""
        return self._parse_system_config(
            await self._request("GET", "/api/v1/system/config")
        )

    async def get_system_sync(self) -> SystemSyncResponse:
        """GET /api/v1/system/sync → SystemSyncResponse"""
        return self._parse_system_sync(
            await self._request("GET", "/api/v1/system/sync")
        )

    async def get_system_stats(self) -> SystemStatsResponse:
        """GET /api/v1/system/stats → SystemStatsResponse"""
        return self._parse_system_stats(
            await self._request("GET", "/api/v1/system/stats")
        )

    async def wait_for_agent_indexed(
        self,
        agent_id: str,
        *,
        timeout: float = 60.0,
    ) -> AgentIndexedResponse:
        """GET /api/v1/system/sync/wait-for-agent → AgentIndexedResponse.

        Single server-side long-poll — the registry blocks internally until
        the agent row appears or *timeout* seconds elapse.  The caller makes
        one HTTP call; no client-side polling loop is needed.

        Raises ``RegistryClientError`` on non-2xx responses (e.g. registry
        unreachable).  Returns normally regardless of ``indexed`` value —
        callers must check ``result.indexed`` and raise / skip as appropriate.
        """
        params = {"agent_id": agent_id, "timeout": timeout}
        return self._parse_agent_indexed(
            await self._request(
                "GET", "/api/v1/system/sync/wait-for-agent",
                params=params,
            )
        )

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
    # /agents/{agent_id}/listings
    # ------------------------------------------------------------------

    async def publish_listing(
        self, agent_id: str, listing: ListingRequest, private_key: str
    ) -> dict:
        """POST /agents/{agent_id}/listings with EIP-191 auth."""
        body, hdrs = self._publish_listing_body(listing, agent_id, private_key)
        return await self._request(
            "POST", f"/agents/{agent_id}/listings",
            json=body, headers=hdrs, expected=(201,),
        )

    async def validate_publish_listing(
        self, request: ValidatePublishRequest
    ) -> ValidatePublishResponse:
        """POST /api/v1/listings/validate-publish — dry-run, no auth, no DB writes.

        Returns ValidatePublishResponse.valid=True when the payload would be
        accepted by publish_listing (ignoring agent registration and auth).
        Use this as the stage-03a pre-flight check before calling resume on
        the storefront.
        """
        data = await self._request(
            "POST", "/api/v1/listings/validate-publish",
            json=request.to_dict(), expected=(200,),
        )
        return ValidatePublishResponse.from_dict(data)

    async def get_agent_listings(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListingListResponse:
        """GET /agents/{agent_id}/listings → ListingListResponse"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        return self._parse_listing_list(
            await self._request("GET", f"/agents/{agent_id}/listings", params=params)
        )

    # ------------------------------------------------------------------
    # /listings
    # ------------------------------------------------------------------

    async def get_filter_spec(self) -> FilterSpecResponse:
        """GET /filter-spec — what the registry advertises.

        Cache by URL+etag and pass ``etag=...`` to :meth:`list_listings`
        to gate the query on the cached spec.
        """
        data = await self._request("GET", "/filter-spec")
        return FilterSpecResponse.from_dict(data)

    async def list_listings(
        self,
        *,
        status: Optional[str] = "open",
        limit: int = 50,
        offset: int = 0,
        etag: str | None = None,
        **filters: Any,
    ) -> ListingListResponse:
        """GET /listings → ListingListResponse.

        ``**filters`` are passthrough query params keyed on filter-spec
        filter names (``gpu_model``, ``ram_gb_min``, ``token``, ...).  Use
        :meth:`get_filter_spec` to discover what's available.  ``etag``
        becomes an ``If-Match`` header; mismatch → ``RegistryClientError``
        with status 412 so the caller can refresh and retry.
        """
        params = self._listings_params(
            status=status, limit=limit, offset=offset, filters=filters,
        )
        return self._parse_listing_list(
            await self._request(
                "GET", "/listings",
                params=params,
                headers=self._if_match_headers(etag),
            )
        )

    async def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /listings/{listing_id} → ListingSummary"""
        data = await self._request("GET", f"/listings/{listing_id}")
        # API wraps the listing in {"listing": {...}}
        return self._parse_listing(data.get("listing", data) if isinstance(data, dict) else data)

    async def update_listing(self, listing_id: str, request: UpdateListingRequest) -> dict:
        """PUT /listings/{listing_id} → updated listing dict."""
        return await self._request("PUT", f"/listings/{listing_id}", json=request.to_dict(listing_id))

    async def delete_listing(self, listing_id: str, private_key: str) -> None:
        """DELETE /listings/{listing_id} with EIP-191 auth query params."""
        params = self._delete_listing_params(listing_id, private_key)
        await self._request("DELETE", f"/listings/{listing_id}", params=params, expected=(204,))


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
        api_key: str | None = None,
    ) -> None:
        """See ``RegistryClient.__init__`` for ``api_key`` semantics."""
        super().__init__(base_url, timeout)
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
            headers=headers,
        )
        log.info(
            "SyncRegistryClient initialised — base_url=%s api_key=%s",
            self._base, "set" if api_key else "none",
        )

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

    def get_system_config(self) -> SystemConfigResponse:
        """GET /api/v1/system/config → SystemConfigResponse"""
        return self._parse_system_config(
            self._request("GET", "/api/v1/system/config")
        )

    def get_system_sync(self) -> SystemSyncResponse:
        """GET /api/v1/system/sync → SystemSyncResponse"""
        return self._parse_system_sync(
            self._request("GET", "/api/v1/system/sync")
        )

    def get_system_stats(self) -> SystemStatsResponse:
        """GET /api/v1/system/stats → SystemStatsResponse"""
        return self._parse_system_stats(
            self._request("GET", "/api/v1/system/stats")
        )

    def wait_for_agent_indexed(
        self,
        agent_id: str,
        *,
        timeout: float = 60.0,
    ) -> AgentIndexedResponse:
        """GET /api/v1/system/sync/wait-for-agent → AgentIndexedResponse.

        Single server-side long-poll — the registry blocks internally until
        the agent row appears or *timeout* seconds elapse.  The caller makes
        one HTTP call; no client-side polling loop is needed.

        **Important:** the underlying ``httpx.Client`` must be configured with
        a read timeout greater than *timeout* (the server-side wait).  The
        ``SyncRegistryClient`` fixture in the e2e conftest sets ``timeout=90.0``
        to cover the default 60 s server poll with headroom.

        Raises ``RegistryClientError`` on non-2xx responses (e.g. registry
        unreachable).  Returns normally regardless of ``indexed`` value —
        callers must check ``result.indexed`` and raise / skip as appropriate.
        """
        params = {"agent_id": agent_id, "timeout": timeout}
        return self._parse_agent_indexed(
            self._request(
                "GET", "/api/v1/system/sync/wait-for-agent",
                params=params,
            )
        )

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
    # /agents/{agent_id}/listings
    # ------------------------------------------------------------------

    def publish_listing(
        self, agent_id: str, listing: ListingRequest, private_key: str
    ) -> dict:
        """POST /agents/{agent_id}/listings with EIP-191 auth."""
        body, hdrs = self._publish_listing_body(listing, agent_id, private_key)
        return self._request(
            "POST", f"/agents/{agent_id}/listings",
            json=body, headers=hdrs, expected=(201,),
        )

    def validate_publish_listing(
        self, request: ValidatePublishRequest
    ) -> ValidatePublishResponse:
        """POST /api/v1/listings/validate-publish — dry-run, no auth, no DB writes.

        Returns ValidatePublishResponse.valid=True when the payload would be
        accepted by publish_listing (ignoring agent registration and auth).
        Use this as the stage-03a pre-flight check before calling resume on
        the storefront.
        """
        data = self._request(
            "POST", "/api/v1/listings/validate-publish",
            json=request.to_dict(), expected=(200,),
        )
        return ValidatePublishResponse.from_dict(data)

    def get_agent_listings(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListingListResponse:
        """GET /agents/{agent_id}/listings → ListingListResponse"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        return self._parse_listing_list(
            self._request("GET", f"/agents/{agent_id}/listings", params=params)
        )

    # ------------------------------------------------------------------
    # /listings
    # ------------------------------------------------------------------

    def get_filter_spec(self) -> FilterSpecResponse:
        """GET /filter-spec — see :meth:`RegistryClient.get_filter_spec`."""
        data = self._request("GET", "/filter-spec")
        return FilterSpecResponse.from_dict(data)

    def list_listings(
        self,
        *,
        status: Optional[str] = "open",
        limit: int = 50,
        offset: int = 0,
        etag: str | None = None,
        **filters: Any,
    ) -> ListingListResponse:
        """GET /listings — see :meth:`RegistryClient.list_listings`."""
        params = self._listings_params(
            status=status, limit=limit, offset=offset, filters=filters,
        )
        return self._parse_listing_list(
            self._request(
                "GET", "/listings",
                params=params,
                headers=self._if_match_headers(etag),
            )
        )

    def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /listings/{listing_id} → ListingSummary"""
        data = self._request("GET", f"/listings/{listing_id}")
        # API wraps the listing in {"listing": {...}}
        return self._parse_listing(data.get("listing", data) if isinstance(data, dict) else data)

    def update_listing(self, listing_id: str, request: UpdateListingRequest) -> dict:
        """PUT /listings/{listing_id} → updated listing dict."""
        return self._request("PUT", f"/listings/{listing_id}", json=request.to_dict(listing_id))

    def delete_listing(self, listing_id: str, private_key: str) -> None:
        """DELETE /listings/{listing_id} with EIP-191 auth query params."""
        params = self._delete_listing_params(listing_id, private_key)
        self._request("DELETE", f"/listings/{listing_id}", params=params, expected=(204,))
