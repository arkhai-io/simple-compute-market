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
        resp = await client.create_order(
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
    StorefrontOrderClaimResponse,
    StorefrontOrderCloseResponse,
    StorefrontOrderCreateResponse,
    StorefrontOrderDiscoverResponse,
    StorefrontOrderRefundResponse,
    ERC8004RegistrationFile,
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
    def __init__(self, base_url: str, private_key: Optional[str], timeout: float) -> None:
        self._base = base_url.rstrip("/")
        self._private_key = private_key
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _auth_headers(self, operation: str, resource_id: str) -> dict[str, str]:
        if not self._private_key:
            return {}
        return _build_auth_headers(self._private_key, operation, resource_id)

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
    ) -> None:
        super().__init__(base_url, private_key, timeout)
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

    async def _get(self, path: str) -> dict:
        url = self._url(path)
        resp = await self._client.get(path, timeout=self._timeout)
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    async def get_registration(self) -> ERC8004RegistrationFile:
        """GET /.well-known/erc-8004-registration.json"""
        return ERC8004RegistrationFile.from_dict(
            await self._get("/.well-known/erc-8004-registration.json")
        )

    async def create_order(
        self,
        *,
        agent_wallet_address: str,
        offer: dict[str, Any],
        demand: dict[str, Any],
        duration_hours: float = 1.0,
    ) -> StorefrontOrderCreateResponse:
        """POST /orders/create"""
        headers = self._auth_headers("create_order", agent_wallet_address)
        body = {"offer": offer, "demand": demand, "duration_hours": duration_hours}
        return StorefrontOrderCreateResponse.from_dict(
            await self._post("/orders/create", body, extra_headers=headers)
        )

    async def close_order(self, order_id: str) -> StorefrontOrderCloseResponse:
        """POST /orders/close"""
        headers = self._auth_headers("close_order", order_id)
        return StorefrontOrderCloseResponse.from_dict(
            await self._post("/orders/close", {"order_id": order_id}, extra_headers=headers)
        )

    async def refund_order(
        self,
        *,
        order_id: str,
        buyer_address: str,
        amount: str | None = None,
        token: str | None = None,
    ) -> StorefrontOrderRefundResponse:
        """POST /orders/refund"""
        headers = self._auth_headers("refund_order", order_id)
        body: dict[str, Any] = {"order_id": order_id, "buyer_address": buyer_address}
        if amount is not None:
            body["amount"] = amount
        if token is not None:
            body["token"] = token
        return StorefrontOrderRefundResponse.from_dict(
            await self._post("/orders/refund", body, extra_headers=headers)
        )

    async def claim_order(
        self,
        *,
        order_id: str,
        fulfillment_uid: str | None = None,
    ) -> StorefrontOrderClaimResponse:
        """POST /orders/claim"""
        headers = self._auth_headers("claim_order", order_id)
        body: dict[str, Any] = {"order_id": order_id}
        if fulfillment_uid:
            body["fulfillment_uid"] = fulfillment_uid
        return StorefrontOrderClaimResponse.from_dict(
            await self._post("/orders/claim", body, extra_headers=headers)
        )

    async def discover_orders(
        self,
        *,
        order_id: str,
        include_active: bool = False,
    ) -> StorefrontOrderDiscoverResponse:
        """POST /orders/discover"""
        headers = self._auth_headers("discover_orders", order_id)
        body = {"order_id": order_id, "include_active": include_active}
        return StorefrontOrderDiscoverResponse.from_dict(
            await self._post("/orders/discover", body, extra_headers=headers)
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
    ) -> None:
        super().__init__(base_url, private_key, timeout)
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

    def _get(self, path: str) -> dict:
        url = self._url(path)
        resp = self._client.get(path, timeout=self._timeout)
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    def get_registration(self) -> ERC8004RegistrationFile:
        """GET /.well-known/erc-8004-registration.json"""
        return ERC8004RegistrationFile.from_dict(
            self._get("/.well-known/erc-8004-registration.json")
        )

    def create_order(
        self,
        *,
        agent_wallet_address: str,
        offer: dict[str, Any],
        demand: dict[str, Any],
        duration_hours: float = 1.0,
    ) -> StorefrontOrderCreateResponse:
        """POST /orders/create"""
        headers = self._auth_headers("create_order", agent_wallet_address)
        body = {"offer": offer, "demand": demand, "duration_hours": duration_hours}
        return StorefrontOrderCreateResponse.from_dict(
            self._post("/orders/create", body, extra_headers=headers)
        )

    def close_order(self, order_id: str) -> StorefrontOrderCloseResponse:
        """POST /orders/close"""
        headers = self._auth_headers("close_order", order_id)
        return StorefrontOrderCloseResponse.from_dict(
            self._post("/orders/close", {"order_id": order_id}, extra_headers=headers)
        )

    def refund_order(
        self,
        *,
        order_id: str,
        buyer_address: str,
        amount: str | None = None,
        token: str | None = None,
    ) -> StorefrontOrderRefundResponse:
        """POST /orders/refund"""
        headers = self._auth_headers("refund_order", order_id)
        body: dict[str, Any] = {"order_id": order_id, "buyer_address": buyer_address}
        if amount is not None:
            body["amount"] = amount
        if token is not None:
            body["token"] = token
        return StorefrontOrderRefundResponse.from_dict(
            self._post("/orders/refund", body, extra_headers=headers)
        )

    def claim_order(
        self,
        *,
        order_id: str,
        fulfillment_uid: str | None = None,
    ) -> StorefrontOrderClaimResponse:
        """POST /orders/claim"""
        headers = self._auth_headers("claim_order", order_id)
        body: dict[str, Any] = {"order_id": order_id}
        if fulfillment_uid:
            body["fulfillment_uid"] = fulfillment_uid
        return StorefrontOrderClaimResponse.from_dict(
            self._post("/orders/claim", body, extra_headers=headers)
        )

    def discover_orders(
        self,
        *,
        order_id: str,
        include_active: bool = False,
    ) -> StorefrontOrderDiscoverResponse:
        """POST /orders/discover"""
        headers = self._auth_headers("discover_orders", order_id)
        body = {"order_id": order_id, "include_active": include_active}
        return StorefrontOrderDiscoverResponse.from_dict(
            self._post("/orders/discover", body, extra_headers=headers)
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
