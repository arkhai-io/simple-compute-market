"""HTTP clients for the Arkhai registry REST API.

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
    FilterSpecResponse,
    HealthResponse,
    ListingListResponse,
    ListingRequest,
    ListingSummary,
    Publisher,
    PublisherListResponse,
    SystemStatsResponse,
    UpdateListingRequest,
    ValidatePublishRequest,
    ValidatePublishResponse,
)

log = logging.getLogger(__name__)


def _eip191_address(private_key: str) -> str:
    """Lowercased EIP-191 wallet address for ``private_key``."""
    from eth_account import Account

    return Account.from_key(private_key).address.lower()


# ---------------------------------------------------------------------------
# Shared logic — route construction, auth, response parsing
# ---------------------------------------------------------------------------


class _RegistryClientBase:
    """Route paths, auth helpers, and response parsers shared by both clients.

    Subclasses supply ``_request`` that performs the actual HTTP call (async or
    sync).  This base class never touches the network directly.
    """

    def __init__(self, base_url: str, timeout: float) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    @staticmethod
    def _listings_params(
        *,
        status: str | None,
        publisher: str | None,
        limit: int,
        offset: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        """Build query params for GET /listings.

        ``filters`` is an opaque dict keyed on the registry's filter-spec
        names — the client doesn't enumerate them.  Bool values are
        stringified ("true"/"false") since FastAPI parses query bools from
        those literals.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if publisher is not None:
            params["publisher"] = publisher
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
    def _publish_listing_body(listing: ListingRequest, private_key: str) -> tuple[dict, dict]:
        """Returns (json_body, headers) for a publish POST /listings.

        The signing identity is derived from ``private_key``; the registry
        verifies the signature over ``create_listing:<identifier>:<timestamp>``
        and creates the publisher lazily.
        """
        identifier = _eip191_address(private_key)
        auth = build_auth_headers(private_key, "create_listing", identifier)
        body = {
            **listing.to_dict(),
            "scheme": "eip191",
            "identifier": identifier,
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
    def _parse_publisher(data: dict) -> Publisher:
        return Publisher.from_dict(data)

    @staticmethod
    def _parse_publisher_list(data: Any) -> PublisherListResponse:
        return PublisherListResponse.from_raw(data)

    @staticmethod
    def _parse_listing_list(data: Any) -> ListingListResponse:
        return ListingListResponse.from_raw(data)

    @staticmethod
    def _parse_listing(data: dict) -> ListingSummary:
        return ListingSummary.from_dict(data)

    @staticmethod
    def _parse_system_stats(data: dict) -> SystemStatsResponse:
        return SystemStatsResponse.from_dict(data)


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class RegistryClient(_RegistryClientBase):
    """Async HTTP client for the Arkhai registry REST API.

    Parameters
    ----------
    base_url:
        Base URL of the registry service (e.g. ``http://localhost:8080``).
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.AsyncBaseTransport`` to inject.  Primarily used in
        tests to supply ``httpx.ASGITransport(app=app)`` for in-process calls.
    api_key:
        Optional bearer token sent on every request as
        ``Authorization: Bearer <key>``.  Layered on top of per-call EIP-191
        signing (publish/delete) — both can be required in parallel.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
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
    # /health, /stats
    # ------------------------------------------------------------------

    async def get_health(self) -> HealthResponse:
        """GET /health → HealthResponse"""
        return self._parse_health(await self._request("GET", "/health"))

    async def get_system_stats(self) -> SystemStatsResponse:
        """GET /api/v1/system/stats → SystemStatsResponse"""
        return self._parse_system_stats(
            await self._request("GET", "/api/v1/system/stats")
        )

    # ------------------------------------------------------------------
    # /publishers
    # ------------------------------------------------------------------

    async def list_publishers(
        self,
        *,
        identifier: str | None = None,
        scheme: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PublisherListResponse:
        """GET /publishers → PublisherListResponse.

        With ``identifier`` set, resolves the publisher owning that signing
        identity (the result list holds zero or one publisher).
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if identifier is not None:
            params["identifier"] = identifier
        if scheme is not None:
            params["scheme"] = scheme
        return self._parse_publisher_list(
            await self._request("GET", "/publishers", params=params)
        )

    async def get_publisher(self, publisher_id: int) -> Publisher:
        """GET /publishers/{publisher_id} → Publisher"""
        return self._parse_publisher(
            await self._request("GET", f"/publishers/{publisher_id}")
        )

    # ------------------------------------------------------------------
    # /listings
    # ------------------------------------------------------------------

    async def publish_listing(self, listing: ListingRequest, private_key: str) -> dict:
        """POST /listings with EIP-191 auth (signer derived from the key)."""
        body, hdrs = self._publish_listing_body(listing, private_key)
        return await self._request(
            "POST", "/listings", json=body, headers=hdrs, expected=(201,),
        )

    async def validate_publish_listing(
        self, request: ValidatePublishRequest
    ) -> ValidatePublishResponse:
        """POST /api/v1/listings/validate-publish — dry-run, no auth, no DB writes."""
        data = await self._request(
            "POST", "/api/v1/listings/validate-publish",
            json=request.to_dict(), expected=(200,),
        )
        return ValidatePublishResponse.from_dict(data)

    async def get_filter_spec(self) -> FilterSpecResponse:
        """GET /filter-spec — what the registry advertises."""
        data = await self._request("GET", "/filter-spec")
        return FilterSpecResponse.from_dict(data)

    async def list_listings(
        self,
        *,
        status: Optional[str] = "open",
        publisher: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        etag: str | None = None,
        **filters: Any,
    ) -> ListingListResponse:
        """GET /listings → ListingListResponse.

        ``publisher`` narrows to one publisher (by signing identifier).
        ``**filters`` are passthrough query params keyed on filter-spec
        names; ``etag`` becomes an ``If-Match`` header (mismatch → 412).
        """
        params = self._listings_params(
            status=status, publisher=publisher, limit=limit, offset=offset, filters=filters,
        )
        return self._parse_listing_list(
            await self._request(
                "GET", "/listings",
                params=params,
                headers=self._if_match_headers(etag),
            )
        )

    async def list_listings_for_publisher(
        self, identifier: str, *, status: Optional[str] = None, limit: int = 50, offset: int = 0,
    ) -> ListingListResponse:
        """GET /listings?publisher=<identifier> → a publisher's listings."""
        return await self.list_listings(
            status=status, publisher=identifier, limit=limit, offset=offset,
        )

    async def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /listings/{listing_id} → ListingSummary"""
        data = await self._request("GET", f"/listings/{listing_id}")
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
    """Synchronous HTTP client for the Arkhai registry REST API.

    Identical method signatures to ``RegistryClient`` but blocking.  Suitable
    for synchronous test suites and scripts.  ``transport=`` accepts
    ``httpx.ASGITransport(app=app)`` to drive FastAPI in-process.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
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
    # /health, /stats
    # ------------------------------------------------------------------

    def get_health(self) -> HealthResponse:
        """GET /health → HealthResponse"""
        return self._parse_health(self._request("GET", "/health"))

    def get_system_stats(self) -> SystemStatsResponse:
        """GET /api/v1/system/stats → SystemStatsResponse"""
        return self._parse_system_stats(self._request("GET", "/api/v1/system/stats"))

    # ------------------------------------------------------------------
    # /publishers
    # ------------------------------------------------------------------

    def list_publishers(
        self,
        *,
        identifier: str | None = None,
        scheme: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PublisherListResponse:
        """GET /publishers → PublisherListResponse."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if identifier is not None:
            params["identifier"] = identifier
        if scheme is not None:
            params["scheme"] = scheme
        return self._parse_publisher_list(self._request("GET", "/publishers", params=params))

    def get_publisher(self, publisher_id: int) -> Publisher:
        """GET /publishers/{publisher_id} → Publisher"""
        return self._parse_publisher(self._request("GET", f"/publishers/{publisher_id}"))

    # ------------------------------------------------------------------
    # /listings
    # ------------------------------------------------------------------

    def publish_listing(self, listing: ListingRequest, private_key: str) -> dict:
        """POST /listings with EIP-191 auth (signer derived from the key)."""
        body, hdrs = self._publish_listing_body(listing, private_key)
        return self._request(
            "POST", "/listings", json=body, headers=hdrs, expected=(201,),
        )

    def validate_publish_listing(
        self, request: ValidatePublishRequest
    ) -> ValidatePublishResponse:
        """POST /api/v1/listings/validate-publish — dry-run, no auth, no DB writes."""
        data = self._request(
            "POST", "/api/v1/listings/validate-publish",
            json=request.to_dict(), expected=(200,),
        )
        return ValidatePublishResponse.from_dict(data)

    def get_filter_spec(self) -> FilterSpecResponse:
        """GET /filter-spec — see :meth:`RegistryClient.get_filter_spec`."""
        data = self._request("GET", "/filter-spec")
        return FilterSpecResponse.from_dict(data)

    def list_listings(
        self,
        *,
        status: Optional[str] = "open",
        publisher: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        etag: str | None = None,
        **filters: Any,
    ) -> ListingListResponse:
        """GET /listings — see :meth:`RegistryClient.list_listings`."""
        params = self._listings_params(
            status=status, publisher=publisher, limit=limit, offset=offset, filters=filters,
        )
        return self._parse_listing_list(
            self._request(
                "GET", "/listings",
                params=params,
                headers=self._if_match_headers(etag),
            )
        )

    def list_listings_for_publisher(
        self, identifier: str, *, status: Optional[str] = None, limit: int = 50, offset: int = 0,
    ) -> ListingListResponse:
        """GET /listings?publisher=<identifier> → a publisher's listings."""
        return self.list_listings(
            status=status, publisher=identifier, limit=limit, offset=offset,
        )

    def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /listings/{listing_id} → ListingSummary"""
        data = self._request("GET", f"/listings/{listing_id}")
        return self._parse_listing(data.get("listing", data) if isinstance(data, dict) else data)

    def update_listing(self, listing_id: str, request: UpdateListingRequest) -> dict:
        """PUT /listings/{listing_id} → updated listing dict."""
        return self._request("PUT", f"/listings/{listing_id}", json=request.to_dict(listing_id))

    def delete_listing(self, listing_id: str, private_key: str) -> None:
        """DELETE /listings/{listing_id} with EIP-191 auth query params."""
        params = self._delete_listing_params(listing_id, private_key)
        self._request("DELETE", f"/listings/{listing_id}", params=params, expected=(204,))
