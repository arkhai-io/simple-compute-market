"""Synchronous HTTP client for the Arkhai agent REST API.

This is the integration-test shim over the canonical async client in
``agent.client.agent_client``.  It uses httpx for synchronous I/O but
delegates EIP-191 signing to the canonical ``_build_auth_headers``
helper so both clients stay in sync with the server's auth protocol.

Auth
----
The signed message format (from agent.py ``_check_agent_request_auth``):

    create_order  →  "create_order:<agent_wallet_address>:<timestamp>"
    close_order   →  "close_order:<order_id>:<timestamp>"

``agent_wallet_address`` is the ``AGENT_WALLET_ADDRESS`` setting on the
target agent, available in test config as ``buyer.wallet_address`` /
``seller.wallet_address``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent_client.client import AgentClientError, _build_auth_headers
from src.models.agent import ERC8004RegistrationFile
from src.eip191_http_client import ApiError

log = logging.getLogger(__name__)


class _OrderResponse:
    """Thin wrapper around the raw JSON response from /orders/create and /orders/close."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def status(self) -> str:
        return self._data.get("status", "")

    @property
    def order_id(self) -> str | None:
        return self._data.get("order_id")

    @property
    def event_id(self) -> str | None:
        return self._data.get("event_id")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class AgentClient:
    """Synchronous HTTP client for the Arkhai agent REST API.

    Parameters
    ----------
    base_url:
        Publicly-reachable URL of the agent.
    private_key:
        Caller's EIP-191 private key used to sign ``X-Signature`` headers.
    agent_wallet_address:
        Wallet address of the target agent.  Used as ``resource_id`` in
        the ``create_order`` signed message.  Falls back to ``base_url``
        if not supplied (backward-compat — agents without
        ``AGENT_WALLET_ADDRESS`` set skip auth).
    timeout:
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        private_key: str,
        *,
        agent_wallet_address: str | None = None,
        # Legacy kwarg name kept for backward compat with existing test fixtures
        agent_base_url_override: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._private_key = private_key
        # Prefer explicit wallet_address; fall back to legacy base_url_override
        # (which was wrong — kept only to avoid breaking callers mid-refactor).
        self._agent_wallet_address = agent_wallet_address or agent_base_url_override or base_url
        self._http = httpx.Client(
            base_url=self._base,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        log.info("AgentClient initialised — base_url=%s", self._base)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        extra_headers: dict[str, str] | None = None,
        expected_statuses: tuple[int, ...] = (200, 201),
    ) -> dict[str, Any]:
        headers = dict(extra_headers or {})
        resp = self._http.request(method, path, json=json, headers=headers)
        if resp.status_code not in expected_statuses:
            raise ApiError(method, f"{self._base}{path}", resp.status_code, resp.text)
        return resp.json()

    # ------------------------------------------------------------------
    # ERC-8004 registration
    # ------------------------------------------------------------------

    def get_registration_file(self) -> "ERC8004RegistrationFile":
        """GET /.well-known/erc-8004-registration.json"""
        data = self._request("GET", "/.well-known/erc-8004-registration.json")
        return ERC8004RegistrationFile.from_dict(data)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def create_order(self, order: Any) -> _OrderResponse:
        """POST /orders/create with EIP-191 signed headers.

        ``order`` may be an ``AgentOrderCreateRequest`` (with ``.to_dict()``)
        or a plain dict.
        """
        headers = _build_auth_headers(
            self._private_key, "create_order", self._agent_wallet_address
        )
        body = order.to_dict() if hasattr(order, "to_dict") else dict(order)
        data = self._request("POST", "/orders/create", json=body, extra_headers=headers)
        return _OrderResponse(data)

    def close_order(self, order_id: str) -> _OrderResponse:
        """POST /orders/close with EIP-191 signed headers."""
        headers = _build_auth_headers(self._private_key, "close_order", order_id)
        data = self._request(
            "POST", "/orders/close", json={"order_id": order_id}, extra_headers=headers
        )
        return _OrderResponse(data)

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def send_resource_alert(self, alert: Any) -> dict[str, Any]:
        """POST /alerts/resource (no auth required)."""
        body = alert.to_dict() if hasattr(alert, "to_dict") else dict(alert)
        return self._request(
            "POST",
            "/alerts/resource",
            json=body,
            extra_headers={"Content-Type": "application/json"},
        )