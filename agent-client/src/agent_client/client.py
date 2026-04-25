"""HTTP client for the Arkhai agent's custom REST API.

Covers the Arkhai-specific routes added on top of the A2A protocol:

    POST /alerts/resource
    POST /orders/create
    POST /orders/close
    GET  /.well-known/erc-8004-registration.json

A2A protocol endpoints (agent card, task management) are part of the
``a2a-sdk`` and are not duplicated here.

Auth
----
``create_order`` and ``close_order`` require EIP-191 signed headers.
The server verifies the signature against its configured
``AGENT_WALLET_ADDRESS``.  Message format::

    create_order  →  "create_order:<agent_wallet_address>:<timestamp>"
    close_order   →  "close_order:<order_id>:<timestamp>"

Callers must supply ``private_key`` at construction time.  Requests to
agents that have ``AGENT_WALLET_ADDRESS`` unset (backward-compat / test
mode) still work — the server skips auth when the address is not
configured, and the signed headers are sent but ignored.

Usage::

    from agent.client.agent_client import AgentClient
    import aiohttp

    client = AgentClient(
        "http://seller-agent:8001",
        private_key="0xdeadbeef...",
    )
    async with aiohttp.ClientSession() as session:
        resp = await client.create_order(
            session,
            agent_wallet_address="0xSellerWalletAddress",
            offer={...},
            demand={...},
        )
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


class AgentClientError(Exception):
    """HTTP or protocol error from the agent API."""


def _sign_eip191(private_key: str, message: str) -> str:
    """Sign *message* with *private_key* using EIP-191 personal_sign.

    Returns the hex signature string (without 0x prefix, matching the
    format produced by the stale ``eip191_http_client`` helper).
    """
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


class AgentClient:
    """Async HTTP client for the Arkhai agent's custom REST API.

    Parameters
    ----------
    base_url:
        Base URL of the agent (e.g. ``http://localhost:8001``).
    private_key:
        Caller's EIP-191 private key used to sign ``X-Signature`` auth
        headers.  When ``None`` auth headers are omitted — only works if
        the target agent has ``AGENT_WALLET_ADDRESS`` unset.
    timeout:
        Default HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        private_key: Optional[str] = None,
        *,
        timeout: float = 60.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._private_key = private_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self, operation: str, resource_id: str) -> dict[str, str]:
        """Return signed auth headers, or empty dict if no private key set."""
        if not self._private_key:
            return {}
        return _build_auth_headers(self._private_key, operation, resource_id)

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
        async with session.post(url, json=body, headers=headers, timeout=self._timeout) as resp:
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
        async with session.get(url, timeout=self._timeout) as resp:
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

        Forwards a resource imbalance alert to the agent.  No auth
        required on this route.
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
        agent_wallet_address: str,
        offer: dict[str, Any],
        demand: dict[str, Any],
        duration_hours: float = 1.0,
    ) -> dict[str, Any]:
        """``POST /orders/create``

        Instructs the agent to create a new market order.

        The signed message is
        ``"create_order:<agent_wallet_address>:<timestamp>"``.

        Parameters
        ----------
        agent_wallet_address:
            Wallet address of the target agent (``AGENT_WALLET_ADDRESS``
            on the server side).  Used as the ``resource_id`` in the
            EIP-191 signed message.
        offer:
            Resource the agent offers.
        demand:
            Resource the agent demands.
        duration_hours:
            Requested duration of the compute lease in hours.
        """
        headers = self._auth_headers("create_order", agent_wallet_address)
        body = {
            "offer": offer,
            "demand": demand,
            "duration_hours": duration_hours,
        }
        return await self._post(session, "/orders/create", body, extra_headers=headers)

    async def close_order(
        self,
        session: aiohttp.ClientSession,
        order_id: str,
    ) -> dict[str, Any]:
        """``POST /orders/close``

        Instructs the agent to close an existing market order.

        The signed message is ``"close_order:<order_id>:<timestamp>"``.

        Parameters
        ----------
        order_id:
            The ID of the order to close.  Also used as the
            ``resource_id`` in the EIP-191 signed message.
        """
        headers = self._auth_headers("close_order", order_id)
        body = {"order_id": order_id}
        return await self._post(session, "/orders/close", body, extra_headers=headers)

    # ------------------------------------------------------------------
    # ERC-8004 registration
    # ------------------------------------------------------------------

    async def get_registration(
        self,
        session: aiohttp.ClientSession,
    ) -> dict[str, Any]:
        """``GET /.well-known/erc-8004-registration.json``"""
        return await self._get(session, "/.well-known/erc-8004-registration.json")
