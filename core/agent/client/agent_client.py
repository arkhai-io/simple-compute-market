"""HTTP client for the Arkhai agent's custom REST API.

Covers the Arkhai-specific routes added on top of the A2A protocol:

    POST /alerts/resource
    POST /orders/create
    POST /orders/close
    GET  /.well-known/erc-8004-registration.json

A2A protocol endpoints (agent card, task management) are part of the
``a2a-sdk`` and are not duplicated here.

Usage::

    from agent.client.agent_client import AgentClient
    client = AgentClient("http://seller-agent:8001")
    async with aiohttp.ClientSession() as session:
        resp = await client.create_order(session, offer={...}, demand={...})
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


class AgentClientError(Exception):
    """HTTP or protocol error from the agent API."""


class AgentClient:
    """Async HTTP client for the Arkhai agent's custom REST API.

    Parameters
    ----------
    base_url:
        Base URL of the agent (e.g. ``http://localhost:8001``).
    wallet_address:
        Agent wallet address used to verify ``X-Signature`` auth.
        When ``None`` the auth headers are omitted — only works if the
        target agent has ``AGENT_WALLET_ADDRESS`` unset (backward-compat mode).
    """

    def __init__(
        self,
        base_url: str,
        wallet_address: Optional[str] = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._wallet_address = wallet_address

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self, operation: str, resource_id: str) -> dict[str, str]:
        """Build ``X-Signature`` / ``X-Timestamp`` headers for a signed request.

        Returns an empty dict if ``wallet_address`` was not provided.
        Callers that set ``AGENT_WALLET_ADDRESS`` on the target agent
        must supply a ``wallet_address`` here; otherwise all mutating
        requests will be rejected with 403.
        """
        if not self._wallet_address:
            return {}
        import time
        from eth_account import Account
        from eth_account.messages import encode_defunct
        ts = int(time.time())
        message = f"{operation}:{resource_id}:{ts}"
        msg = encode_defunct(text=message)
        # NOTE: signing requires the private key, not just the address.
        # This stub shows the intended interface; callers that need real
        # auth should subclass and override _auth_headers, or pass a
        # pre-built headers dict into each call.
        raise NotImplementedError(
            "AgentClient._auth_headers: signing requires a private key. "
            "Subclass AgentClient and override _auth_headers, or set "
            "AGENT_WALLET_ADDRESS to empty on the target agent to skip auth."
        )

    async def _post(
        self,
        session: aiohttp.ClientSession,
        path: str,
        body: dict[str, Any],
        *,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        headers = dict(extra_headers or {})
        async with session.post(url, json=body, headers=headers) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise AgentClientError(
                    f"POST {path} returned {resp.status}: {text[:200]}"
                )
            return await resp.json()

    async def _get(
        self,
        session: aiohttp.ClientSession,
        path: str,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        async with session.get(url) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise AgentClientError(
                    f"GET {path} returned {resp.status}: {text[:200]}"
                )
            return await resp.json()

    # ------------------------------------------------------------------
    # Alert endpoint
    # ------------------------------------------------------------------

    async def send_resource_alert(
        self,
        session: aiohttp.ClientSession,
        *,
        event_type: str = "resource_imbalance",
        resource: dict[str, Any],
        value: float,
        label: str,
        threshold: str,
    ) -> dict[str, Any]:
        """``POST /alerts/resource``

        Forwards a resource imbalance alert to the agent.  The agent
        will route the alert through its policy engine.

        Parameters
        ----------
        resource:
            Dict with keys: ``gpu_model``, ``quantity``, ``sla``, ``region``.
        value:
            Utilisation value in ``[0.0, 1.0]``.
        label:
            Human-readable alert label (e.g. ``'LOW UTILIZATION'``).
        threshold:
            Threshold string (e.g. ``'<=0.30'``).
        """
        body = {
            "event_type": event_type,
            "resource": resource,
            "value": value,
            "label": label,
            "threshold": threshold,
        }
        return await self._post(session, "/alerts/resource", body)

    # ------------------------------------------------------------------
    # Order endpoints
    # ------------------------------------------------------------------

    async def create_order(
        self,
        session: aiohttp.ClientSession,
        *,
        offer: dict[str, Any],
        demand: dict[str, Any],
        duration_hours: float = 1.0,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """``POST /orders/create``

        Instructs the agent to create a new market order.

        Parameters
        ----------
        offer:
            Resource the agent offers.  One of ``offer``/``demand`` must be
            a compute resource (with ``gpu_model``, ``quantity``, ``sla``,
            ``region``) and the other a token resource (with ``token``,
            ``amount``).
        demand:
            Resource the agent demands.
        duration_hours:
            Requested duration of the compute lease in hours.
        extra_headers:
            Optional additional HTTP headers (e.g. pre-built auth headers).
        """
        body = {
            "offer": offer,
            "demand": demand,
            "duration_hours": duration_hours,
        }
        return await self._post(
            session, "/orders/create", body, extra_headers=extra_headers
        )

    async def close_order(
        self,
        session: aiohttp.ClientSession,
        order_id: str,
        *,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """``POST /orders/close``

        Instructs the agent to close an existing market order.

        Parameters
        ----------
        order_id:
            The ID of the order to close.
        extra_headers:
            Optional additional HTTP headers (e.g. pre-built auth headers).
        """
        body = {"order_id": order_id}
        return await self._post(
            session, "/orders/close", body, extra_headers=extra_headers
        )

    # ------------------------------------------------------------------
    # ERC-8004 registration
    # ------------------------------------------------------------------

    async def get_registration(
        self,
        session: aiohttp.ClientSession,
    ) -> dict[str, Any]:
        """``GET /.well-known/erc-8004-registration.json``

        Returns the agent's ERC-8004 registration document.
        """
        return await self._get(session, "/.well-known/erc-8004-registration.json")
