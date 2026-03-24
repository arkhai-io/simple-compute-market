"""
The agent validates X-Signature / X-Timestamp headers using EIP-191.
Message format:
  create_order  →  "create_order:<BASE_URL_OVERRIDE>:<timestamp>"
  close_order   →  "close_order:<order_id>:<timestamp>"

The resource_id for create_order is the agent's own BASE_URL_OVERRIDE
(its public base URL), not the caller's URL.  We pass it as a constructor
argument so it can be read from config alongside the agent's api_url.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from src.eip191_http_client import ApiError, build_auth_headers, sign_eip191
from src.models.agent import (
    AgentOrderCloseRequest,
    AgentOrderCloseResponse,
    AgentOrderCreateRequest,
    AgentOrderCreateResponse,
    ERC8004RegistrationFile,
    ResourceAlertRequest,
)

log = logging.getLogger(__name__)


class AgentClient:
    """
    Synchronous HTTP client for the Agent REST API.

    Parameters
    ----------
    base_url:
        Publicly-reachable URL of the agent (e.g. ``http://buy_agent:8000``).
    agent_base_url_override:
        The value of BASE_URL_OVERRIDE configured inside the agent process.
        This is used as the resource_id when building the create_order auth
        message: ``"create_order:<agent_base_url_override>:<timestamp>"``.
        If None, ``base_url`` is used as a fallback.
    private_key:
        Caller's private key used to sign auth headers.
    timeout:
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        private_key: str,
        *,
        agent_base_url_override: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._private_key = private_key
        # The agent checks the signature against its own wallet address,
        # and the signed message uses BASE_URL_OVERRIDE as the resource_id
        # for create_order.  Fall back to base_url if not explicitly provided.
        self._agent_base_url = (agent_base_url_override or base_url).rstrip("/")
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        log.info("AgentClient initialised — base_url=%s", self._base_url)

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
        headers: dict | None = None,
        expected_statuses: tuple[int, ...] = (200, 201),
    ) -> httpx.Response:
        log.debug("%s %s", method, path)
        resp = self._http.request(method, path, json=json, headers=headers)
        if resp.status_code not in expected_statuses:
            raise ApiError(method, f"{self._base_url}{path}", resp.status_code, resp.text)
        return resp

    # ------------------------------------------------------------------
    # ERC-8004 registration file
    # ------------------------------------------------------------------

    def get_registration_file(self) -> ERC8004RegistrationFile:
        """GET /.well-known/erc-8004-registration.json"""
        resp = self._request("GET", "/.well-known/erc-8004-registration.json")
        return ERC8004RegistrationFile.from_dict(resp.json())

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def create_order(self, order: AgentOrderCreateRequest) -> AgentOrderCreateResponse:
        """
        POST /orders/create

        Auth message: ``"create_order:<agent_base_url_override>:<timestamp>"``
        """
        headers = build_auth_headers(self._private_key, "create_order", self._agent_base_url)
        resp = self._request("POST", "/orders/create", json=order.to_dict(), headers=headers)
        return AgentOrderCreateResponse.from_dict(resp.json())

    def close_order(self, order_id: str) -> AgentOrderCloseResponse:
        """
        POST /orders/close

        Auth message: ``"close_order:<order_id>:<timestamp>"``
        """
        headers = build_auth_headers(self._private_key, "close_order", order_id)
        body = AgentOrderCloseRequest(order_id=order_id)
        resp = self._request("POST", "/orders/close", json=body.to_dict(), headers=headers)
        return AgentOrderCloseResponse.from_dict(resp.json())

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def send_resource_alert(self, alert: ResourceAlertRequest) -> dict[str, Any]:
        """
        POST /alerts/resource

        No auth is required on this route (the agent does not call
        _check_agent_request_auth before handle_resource_alert).
        Returns the raw response dict which echoes the alert plus
        ``root_agent_response``.
        """
        resp = self._request(
            "POST",
            "/alerts/resource",
            json=alert.to_dict(),
            headers={"Content-Type": "application/json"},
        )
        return resp.json()
