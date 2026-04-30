"""HTTP clients for the Arkhai storefront REST API.

Two clients with identical method signatures:

``StorefrontClient``      — async, backed by ``httpx.AsyncClient``
``SyncStorefrontClient``  — sync,  backed by ``httpx.Client``

Both clients:
- Own their HTTP session internally — callers never create or pass a session.
- Accept a ``transport=`` kwarg at construction for in-process test injection.
- Raise ``StorefrontClientError`` on non-2xx responses.
- Return typed model objects from all methods.

Usage (async)::

    from storefront_client import StorefrontClient

    client = StorefrontClient("http://seller-storefront:8001", private_key="0x...")
    async with client:
        reg = await client.get_registration()
        resp = await client.create_listing(
            agent_wallet_address="0xSellerWallet",
            offer={...},
            demand={...},
        )

Usage (sync, e.g. smoke tests)::

    from storefront_client import SyncStorefrontClient

    client = SyncStorefrontClient("http://seller-storefront:8001", private_key="0x...")
    reg = client.get_registration()
    client.close()
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from storefront_client.models import (
    DiscoverMatch,
    StorefrontListingClaimResponse,
    StorefrontListingCloseResponse,
    StorefrontListingCreateResponse,
    StorefrontListingDiscoverResponse,
    StorefrontListingRefundResponse,
    ERC8004RegistrationFile,
    HealthResponse,
    ListingListResponse,
    ListingSummary,
    ListingPauseResponse,
    NegotiationListResponse,
    NegotiationDetail,
    NegotiationActionResponse,
    AdminPauseResponse,
    AdminStatusResponse,
)

logger = logging.getLogger(__name__)


class StorefrontClientError(Exception):
    """HTTP or protocol error from the storefront API."""


# ---------------------------------------------------------------------------
# EIP-191 signing helpers — shared by both clients
# ---------------------------------------------------------------------------


def _sign_eip191(private_key: str, message: str) -> str:
    """Sign *message* with *private_key* using EIP-191 personal_sign."""
    from eth_account import Account
    from eth_account.messages import encode_defunct
    msg = encode_defunct(text=message)
    signed = Account.sign_message(msg, private_key=private_key)
    return signed.signature.hex()


def _build_auth_headers(private_key: str, operation: str, resource_id: str) -> dict[str, str]:
    """Build ``X-Signature`` / ``X-Timestamp`` headers for a signed request.

    The signed message is ``"<operation>:<resource_id>:<timestamp>"``.
    """
    timestamp = str(int(time.time()))
    message = f"{operation}:{resource_id}:{timestamp}"
    signature = _sign_eip191(private_key, message)
    return {
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


# ---------------------------------------------------------------------------
# Shared base — route paths, auth, response parsing
# ---------------------------------------------------------------------------


class _StorefrontClientBase:
    def __init__(
        self,
        base_url: str,
        private_key: Optional[str],
        timeout: float,
        admin_key: Optional[str] = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._private_key = private_key
        self._timeout = timeout
        self._admin_key = admin_key

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _auth_headers(self, operation: str, resource_id: str) -> dict[str, str]:
        if not self._private_key:
            return {}
        return _build_auth_headers(self._private_key, operation, resource_id)

    def _admin_headers(self) -> dict[str, str]:
        if not self._admin_key:
            return {}
        return {"X-Admin-Key": self._admin_key}

    @staticmethod
    def _raise_for_status(method: str, url: str, status: int, text: str) -> None:
        if status >= 400:
            raise StorefrontClientError(f"{method} {url} returned {status}: {text[:200]}")


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class StorefrontClient(_StorefrontClientBase):
    """Async HTTP client for the Arkhai storefront REST API.

    Parameters
    ----------
    base_url:
        Base URL of the storefront (e.g. ``http://localhost:8001``).
    private_key:
        EIP-191 private key for signing auth headers. When ``None`` auth
        headers are omitted — only works if the storefront has
        ``AGENT_WALLET_ADDRESS`` unset.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.AsyncBaseTransport`` for in-process test injection.
    """

    def __init__(
        self,
        base_url: str,
        private_key: Optional[str] = None,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        admin_key: Optional[str] = None,
    ) -> None:
        super().__init__(base_url, private_key, timeout, admin_key)
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "StorefrontClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _post(self, path: str, body: dict, *, extra_headers: dict | None = None) -> dict:
        url = self._url(path)
        resp = await self._client.post(
            path, json=body, headers=extra_headers or {}, timeout=self._timeout
        )
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return resp.json()

    async def _get(self, path: str, *, params: dict | None = None) -> dict:
        url = self._url(path)
        resp = await self._client.get(path, params=params or {}, timeout=self._timeout)
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    # ------------------------------------------------------------------
    # System / health
    # ------------------------------------------------------------------

    async def get_health(self) -> HealthResponse:
        """GET /health"""
        return HealthResponse.from_dict(await self._get("/health"))

    async def get_system_status(self) -> HealthResponse:
        """GET /api/v1/system/status — includes paused flag."""
        return HealthResponse.from_dict(await self._get("/api/v1/system/status"))

    # ------------------------------------------------------------------
    # Listings API (GET endpoints unauthenticated; write endpoints admin-key)
    # ------------------------------------------------------------------

    async def list_listings(
        self,
        *,
        status: str | None = None,
        paused: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListingListResponse:
        """GET /api/v1/listings"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if paused is not None:
            params["paused"] = "true" if paused else "false"
        return ListingListResponse.from_dict(
            await self._get("/api/v1/listings", params=params)
        )

    async def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /api/v1/listings/{listing_id}"""
        return ListingSummary.from_dict(
            await self._get(f"/api/v1/listings/{listing_id}")
        )

    async def pause_listing(self, listing_id: str) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/pause  (admin key required)"""
        return ListingPauseResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/pause",
                {},
                extra_headers=self._admin_headers(),
            )
        )

    async def resume_listing(self, listing_id: str) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/resume  (admin key required)"""
        return ListingPauseResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/resume",
                {},
                extra_headers=self._admin_headers(),
            )
        )

    # ------------------------------------------------------------------
    # Negotiations API
    # ------------------------------------------------------------------

    async def list_negotiations(
        self,
        listing_id: str,
        *,
        terminal_state: str | None = None,
        buyer_address: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> "NegotiationListResponse":
        """GET /api/v1/listings/{listing_id}/negotiations"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if terminal_state is not None:
            params["terminal_state"] = terminal_state
        if buyer_address is not None:
            params["buyer_address"] = buyer_address
        return NegotiationListResponse.from_dict(
            await self._get(f"/api/v1/listings/{listing_id}/negotiations", params=params)
        )

    async def get_negotiation(self, listing_id: str, neg_id: str) -> "NegotiationDetail":
        """GET /api/v1/listings/{listing_id}/negotiations/{neg_id}"""
        return NegotiationDetail.from_dict(
            await self._get(f"/api/v1/listings/{listing_id}/negotiations/{neg_id}")
        )

    async def advance_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        action: str,
        price: int | None = None,
        reason: str | None = None,
    ) -> "NegotiationActionResponse":
        """POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/advance  (admin key)"""
        body: dict[str, Any] = {"action": action}
        if price is not None:
            body["price"] = price
        if reason is not None:
            body["reason"] = reason
        return NegotiationActionResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance",
                body,
                extra_headers=self._admin_headers(),
            )
        )

    async def force_accept_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        price: int,
    ) -> "NegotiationActionResponse":
        """POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept  (admin key)"""
        return NegotiationActionResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept",
                {"price": price},
                extra_headers=self._admin_headers(),
            )
        )

    # ------------------------------------------------------------------
    # Admin API
    # ------------------------------------------------------------------

    async def admin_pause(self) -> AdminPauseResponse:
        """POST /admin/pause  (admin key required)"""
        return AdminPauseResponse.from_dict(
            await self._post("/admin/pause", {}, extra_headers=self._admin_headers())
        )

    async def admin_resume(self) -> AdminPauseResponse:
        """POST /admin/resume  (admin key required)"""
        return AdminPauseResponse.from_dict(
            await self._post("/admin/resume", {}, extra_headers=self._admin_headers())
        )

    async def admin_status(self) -> AdminStatusResponse:
        """GET /admin/status  (admin key required)"""
        url = self._url("/admin/status")
        resp = await self._client.get(
            "/admin/status",
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return AdminStatusResponse.from_dict(resp.json())

    async def policy_seed(self) -> dict:
        """POST /admin/policy/seed — discover callables + seed default policies (admin key)."""
        return await self._post("/admin/policy/seed", {}, extra_headers=self._admin_headers())

    async def policy_status(self) -> dict:
        """GET /api/v1/system/policy — callable registry + seeded policy diagnostic."""
        return await self._get("/api/v1/system/policy")

    async def policy_evaluate(self, *, offer: dict, demand: dict, duration_hours: float = 1.0) -> dict:
        """POST /api/v1/system/policy/evaluate — dry-run an order_create event."""
        return await self._post(
            "/api/v1/system/policy/evaluate",
            {"event_type": "order_create", "offer": offer, "demand": demand, "duration_hours": duration_hours},
        )

    # ------------------------------------------------------------------
    # Existing methods (unchanged)
    # ------------------------------------------------------------------

    async def get_registration(self) -> ERC8004RegistrationFile:
        """GET /.well-known/erc-8004-registration.json"""
        return ERC8004RegistrationFile.from_dict(
            await self._get("/.well-known/erc-8004-registration.json")
        )

    async def create_listing(
        self,
        *,
        agent_wallet_address: str,
        offer: dict[str, Any],
        demand: dict[str, Any],
        duration_hours: float = 1.0,
    ) -> StorefrontListingCreateResponse:
        """POST /listings/create"""
        headers = self._auth_headers("create_listing", agent_wallet_address)
        body = {"offer": offer, "demand": demand, "duration_hours": duration_hours}
        return StorefrontListingCreateResponse.from_dict(
            await self._post("/listings/create", body, extra_headers=headers)
        )

    async def close_listing(self, listing_id: str) -> StorefrontListingCloseResponse:
        """POST /listings/close"""
        headers = self._auth_headers("close_listing", listing_id)
        return StorefrontListingCloseResponse.from_dict(
            await self._post("/listings/close", {"listing_id": listing_id}, extra_headers=headers)
        )

    async def refund_listing(
        self,
        *,
        listing_id: str,
        buyer_address: str,
        amount: str | None = None,
        token: str | None = None,
    ) -> StorefrontListingRefundResponse:
        """POST /listings/refund"""
        headers = self._auth_headers("refund_listing", listing_id)
        body: dict[str, Any] = {"listing_id": listing_id, "buyer_address": buyer_address}
        if amount is not None:
            body["amount"] = amount
        if token is not None:
            body["token"] = token
        return StorefrontListingRefundResponse.from_dict(
            await self._post("/listings/refund", body, extra_headers=headers)
        )

    async def claim_listing(
        self,
        *,
        listing_id: str,
        fulfillment_uid: str | None = None,
    ) -> StorefrontListingClaimResponse:
        """POST /listings/claim"""
        headers = self._auth_headers("claim_listing", listing_id)
        body: dict[str, Any] = {"listing_id": listing_id}
        if fulfillment_uid:
            body["fulfillment_uid"] = fulfillment_uid
        return StorefrontListingClaimResponse.from_dict(
            await self._post("/listings/claim", body, extra_headers=headers)
        )

    async def discover_listings(
        self,
        *,
        listing_id: str,
        include_active: bool = False,
    ) -> StorefrontListingDiscoverResponse:
        """POST /listings/discover"""
        headers = self._auth_headers("discover_listings", listing_id)
        body = {"listing_id": listing_id, "include_active": include_active}
        return StorefrontListingDiscoverResponse.from_dict(
            await self._post("/listings/discover", body, extra_headers=headers)
        )

    async def send_resource_alert(
        self,
        *,
        event_type: str = "resource_imbalance",
        resource: dict[str, Any],
        value: float,
        label: str,
        threshold: str,
    ) -> dict[str, Any]:
        """POST /alerts/resource"""
        body = {
            "event_type": event_type,
            "resource": resource,
            "value": value,
            "label": label,
            "threshold": threshold,
        }
        return await self._post("/alerts/resource", body)


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------


class SyncStorefrontClient(_StorefrontClientBase):
    """Synchronous HTTP client for the Arkhai storefront REST API.

    Identical method signatures to ``StorefrontClient`` but blocking.
    Suitable for synchronous CLI commands, smoke tests, and scripts.

    Parameters
    ----------
    base_url:
        Base URL of the storefront.
    private_key:
        EIP-191 private key for signing auth headers.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.BaseTransport`` for in-process test injection.
    """

    def __init__(
        self,
        base_url: str,
        private_key: Optional[str] = None,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        admin_key: Optional[str] = None,
    ) -> None:
        super().__init__(base_url, private_key, timeout, admin_key)
        self._client = httpx.Client(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SyncStorefrontClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _post(self, path: str, body: dict, *, extra_headers: dict | None = None) -> dict:
        url = self._url(path)
        resp = self._client.post(
            path, json=body, headers=extra_headers or {}, timeout=self._timeout
        )
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return resp.json()

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        url = self._url(path)
        resp = self._client.get(path, params=params or {}, timeout=self._timeout)
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    # ------------------------------------------------------------------
    # System / health
    # ------------------------------------------------------------------

    def get_health(self) -> HealthResponse:
        """GET /health"""
        return HealthResponse.from_dict(self._get("/health"))

    def get_system_status(self) -> HealthResponse:
        """GET /api/v1/system/status — includes paused flag."""
        return HealthResponse.from_dict(self._get("/api/v1/system/status"))

    # ------------------------------------------------------------------
    # Listings API
    # ------------------------------------------------------------------

    def list_listings(
        self,
        *,
        status: str | None = None,
        paused: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListingListResponse:
        """GET /api/v1/listings"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if paused is not None:
            params["paused"] = "true" if paused else "false"
        return ListingListResponse.from_dict(
            self._get("/api/v1/listings", params=params)
        )

    def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /api/v1/listings/{listing_id}"""
        return ListingSummary.from_dict(self._get(f"/api/v1/listings/{listing_id}"))

    def pause_listing(self, listing_id: str) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/pause  (admin key required)"""
        return ListingPauseResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/pause",
                {},
                extra_headers=self._admin_headers(),
            )
        )

    def resume_listing(self, listing_id: str) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/resume  (admin key required)"""
        return ListingPauseResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/resume",
                {},
                extra_headers=self._admin_headers(),
            )
        )

    # ------------------------------------------------------------------
    # Negotiations API
    # ------------------------------------------------------------------

    def list_negotiations(
        self,
        listing_id: str,
        *,
        terminal_state: str | None = None,
        buyer_address: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> NegotiationListResponse:
        """GET /api/v1/listings/{listing_id}/negotiations"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if terminal_state is not None:
            params["terminal_state"] = terminal_state
        if buyer_address is not None:
            params["buyer_address"] = buyer_address
        return NegotiationListResponse.from_dict(
            self._get(f"/api/v1/listings/{listing_id}/negotiations", params=params)
        )

    def get_negotiation(self, listing_id: str, neg_id: str) -> NegotiationDetail:
        """GET /api/v1/listings/{listing_id}/negotiations/{neg_id}"""
        return NegotiationDetail.from_dict(
            self._get(f"/api/v1/listings/{listing_id}/negotiations/{neg_id}")
        )

    def advance_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        action: str,
        price: int | None = None,
        reason: str | None = None,
    ) -> NegotiationActionResponse:
        """POST .../advance  (admin key required)"""
        body: dict[str, Any] = {"action": action}
        if price is not None:
            body["price"] = price
        if reason is not None:
            body["reason"] = reason
        return NegotiationActionResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance",
                body,
                extra_headers=self._admin_headers(),
            )
        )

    def force_accept_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        price: int,
    ) -> NegotiationActionResponse:
        """POST .../force-accept  (admin key required)"""
        return NegotiationActionResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept",
                {"price": price},
                extra_headers=self._admin_headers(),
            )
        )

    # ------------------------------------------------------------------
    # Admin API
    # ------------------------------------------------------------------

    def admin_pause(self) -> AdminPauseResponse:
        """POST /admin/pause  (admin key required)"""
        return AdminPauseResponse.from_dict(
            self._post("/admin/pause", {}, extra_headers=self._admin_headers())
        )

    def admin_resume(self) -> AdminPauseResponse:
        """POST /admin/resume  (admin key required)"""
        return AdminPauseResponse.from_dict(
            self._post("/admin/resume", {}, extra_headers=self._admin_headers())
        )

    def admin_status(self) -> AdminStatusResponse:
        """GET /admin/status  (admin key required)"""
        url = self._url("/admin/status")
        resp = self._client.get(
            "/admin/status",
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return AdminStatusResponse.from_dict(resp.json())

    def policy_seed(self) -> dict:
        """POST /admin/policy/seed — discover callables + seed default policies (admin key)."""
        return self._post("/admin/policy/seed", {}, extra_headers=self._admin_headers())

    def policy_status(self) -> dict:
        """GET /api/v1/system/policy — callable registry + seeded policy diagnostic."""
        return self._get("/api/v1/system/policy")

    def policy_evaluate(self, *, offer: dict, demand: dict, duration_hours: float = 1.0) -> dict:
        """POST /api/v1/system/policy/evaluate — dry-run an order_create event."""
        return self._post(
            "/api/v1/system/policy/evaluate",
            {"event_type": "order_create", "offer": offer, "demand": demand, "duration_hours": duration_hours},
        )

    # ------------------------------------------------------------------
    # Existing methods (unchanged)
    # ------------------------------------------------------------------

    def get_registration(self) -> ERC8004RegistrationFile:
        """GET /.well-known/erc-8004-registration.json"""
        return ERC8004RegistrationFile.from_dict(
            self._get("/.well-known/erc-8004-registration.json")
        )

    def create_listing(
        self,
        *,
        agent_wallet_address: str,
        offer: dict[str, Any],
        demand: dict[str, Any],
        duration_hours: float = 1.0,
        paused: bool = False,
    ) -> StorefrontListingCreateResponse:
        """POST /listings/create

        Pass ``paused=True`` to create the order in local SQLite without
        publishing to the registry.  Call ``resume_order`` to publish.
        """
        headers = self._auth_headers("create_listing", agent_wallet_address)
        body = {"offer": offer, "demand": demand, "duration_hours": duration_hours, "paused": paused}
        return StorefrontListingCreateResponse.from_dict(
            self._post("/listings/create", body, extra_headers=headers)
        )

    def close_listing(self, listing_id: str) -> StorefrontListingCloseResponse:
        """POST /listings/close"""
        headers = self._auth_headers("close_listing", listing_id)
        return StorefrontListingCloseResponse.from_dict(
            self._post("/listings/close", {"listing_id": listing_id}, extra_headers=headers)
        )

    def refund_listing(
        self,
        *,
        listing_id: str,
        buyer_address: str,
        amount: str | None = None,
        token: str | None = None,
    ) -> StorefrontListingRefundResponse:
        """POST /listings/refund"""
        headers = self._auth_headers("refund_listing", listing_id)
        body: dict[str, Any] = {"listing_id": listing_id, "buyer_address": buyer_address}
        if amount is not None:
            body["amount"] = amount
        if token is not None:
            body["token"] = token
        return StorefrontListingRefundResponse.from_dict(
            self._post("/listings/refund", body, extra_headers=headers)
        )

    def claim_listing(
        self,
        *,
        listing_id: str,
        fulfillment_uid: str | None = None,
    ) -> StorefrontListingClaimResponse:
        """POST /listings/claim"""
        headers = self._auth_headers("claim_listing", listing_id)
        body: dict[str, Any] = {"listing_id": listing_id}
        if fulfillment_uid:
            body["fulfillment_uid"] = fulfillment_uid
        return StorefrontListingClaimResponse.from_dict(
            self._post("/listings/claim", body, extra_headers=headers)
        )

    def discover_listings(
        self,
        *,
        listing_id: str,
        include_active: bool = False,
    ) -> StorefrontListingDiscoverResponse:
        """POST /listings/discover"""
        headers = self._auth_headers("discover_listings", listing_id)
        body = {"listing_id": listing_id, "include_active": include_active}
        return StorefrontListingDiscoverResponse.from_dict(
            self._post("/listings/discover", body, extra_headers=headers)
        )

    def send_resource_alert(
        self,
        *,
        event_type: str = "resource_imbalance",
        resource: dict[str, Any],
        value: float,
        label: str,
        threshold: str,
    ) -> dict[str, Any]:
        """POST /alerts/resource"""
        body = {
            "event_type": event_type,
            "resource": resource,
            "value": value,
            "label": label,
            "threshold": threshold,
        }
        return self._post("/alerts/resource", body)
