"""Synchronous shim over the canonical async AgentClient.

This module exists solely to let the synchronous ``test_agents.py`` test
suite call the canonical ``agent_client.AgentClient`` without being
converted to async.  It bridges sync→async via ``asyncio.run()``.

The shim's public interface is intentionally identical to the old
``integration-tests/src/agent_client.py`` so that no test changes are
needed.

See TODO(agent-client-migration) in ARCHITECTURE.md for the planned work
to remove this shim entirely by converting the tests to async and importing
``AgentClient`` from ``agent_client`` directly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from agent_client import (
    AgentClient as _AsyncAgentClient,
    AgentClientError,
    ERC8004RegistrationFile,
    AgentOrderCreateResponse,
    AgentOrderCloseResponse,
)
from src.eip191_http_client import ApiError


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class AgentClient:
    """Synchronous wrapper over the canonical async AgentClient.

    Parameters
    ----------
    base_url:
        Base URL of the agent.
    private_key:
        EIP-191 private key for signing auth headers.
    agent_wallet_address:
        Wallet address of the target agent (resource_id for create_order).
    agent_base_url_override:
        Legacy kwarg alias for agent_wallet_address — kept for backward
        compat with existing fixture call sites.
    timeout:
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        private_key: str,
        *,
        agent_wallet_address: str | None = None,
        agent_base_url_override: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._wallet_address = agent_wallet_address or agent_base_url_override or base_url
        self._async_client = _AsyncAgentClient(
            base_url=base_url,
            private_key=private_key,
            timeout=timeout,
        )
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def close(self) -> None:
        if self._session and not self._session.closed:
            _run(self._session.close())
        self._session = None

    # ------------------------------------------------------------------
    # ERC-8004 registration
    # ------------------------------------------------------------------

    def get_registration_file(self) -> ERC8004RegistrationFile:
        """GET /.well-known/erc-8004-registration.json"""
        try:
            return _run(self._async_client.get_registration(self._get_session()))
        except AgentClientError as exc:
            raise ApiError("GET", "/.well-known/erc-8004-registration.json",
                           0, str(exc)) from exc

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def create_order(self, order: Any) -> AgentOrderCreateResponse:
        """POST /orders/create with EIP-191 signed headers."""
        body = order.to_dict() if hasattr(order, "to_dict") else dict(order)
        try:
            return _run(self._async_client.create_order(
                self._get_session(),
                agent_wallet_address=self._wallet_address,
                offer=body.get("offer", {}),
                demand=body.get("demand", {}),
                duration_hours=body.get("duration_hours", 1.0),
            ))
        except AgentClientError as exc:
            raise ApiError("POST", "/orders/create", 0, str(exc)) from exc

    def close_order(self, order_id: str) -> AgentOrderCloseResponse:
        """POST /orders/close with EIP-191 signed headers."""
        try:
            return _run(self._async_client.close_order(self._get_session(), order_id))
        except AgentClientError as exc:
            raise ApiError("POST", "/orders/close", 0, str(exc)) from exc

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def send_resource_alert(self, alert: Any) -> dict[str, Any]:
        """POST /alerts/resource (no auth required)."""
        body = alert.to_dict() if hasattr(alert, "to_dict") else dict(alert)
        try:
            return _run(self._async_client.send_resource_alert(
                self._get_session(),
                event_type=body.get("event_type", "resource_imbalance"),
                resource=body.get("resource", {}),
                value=body.get("value", 0.0),
                label=body.get("label", ""),
                threshold=body.get("threshold", ""),
            ))
        except AgentClientError as exc:
            raise ApiError("POST", "/alerts/resource", 0, str(exc)) from exc
