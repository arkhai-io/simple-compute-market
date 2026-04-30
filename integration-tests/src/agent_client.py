"""Adapter over SyncStorefrontClient for the smoke test suite.

``test_agents.py`` was written against a shim interface that:
- accepts ``agent_wallet_address`` at construction (stored, used per-call)
- exposes ``get_registration_file()`` (renamed to ``get_registration()`` in the wheel)
- accepts ``create_order(order_req)`` with a single request object

This adapter translates those conventions to the canonical ``SyncStorefrontClient``
interface without any ``asyncio.run()`` indirection — ``SyncStorefrontClient`` is
fully synchronous.

To remove this adapter: update ``test_agents.py`` to:
  1. Import ``SyncStorefrontClient`` from the wheel directly
  2. Pass ``agent_wallet_address`` per-call to ``create_order()``
  3. Call ``get_registration()`` instead of ``get_registration_file()``
  4. Replace ``AgentOrderCreateRequest`` with keyword args
"""

from __future__ import annotations

from typing import Any

from storefront_client import SyncStorefrontClient, StorefrontClientError  # noqa: F401

__all__ = ["AgentClient", "StorefrontClientError"]


class AgentClient:
    """Smoke-test adapter over SyncStorefrontClient.

    Preserves the interface expected by test_agents.py while delegating
    all HTTP work to the canonical SyncStorefrontClient.
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
        self._client = SyncStorefrontClient(
            base_url=base_url,
            private_key=private_key,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def get_registration_file(self):
        """GET /.well-known/erc-8004-registration.json"""
        return self._client.get_registration()

    def create_order(self, order: Any):
        """POST /listings/create — accepts an AgentOrderCreateRequest object."""
        body = order.to_dict() if hasattr(order, "to_dict") else dict(order)
        return self._client.create_listing(
            agent_wallet_address=self._wallet_address,
            offer=body.get("offer", {}),
            demand=body.get("demand", {}),
            duration_hours=body.get("duration_hours", 1.0),
        )

    def close_order(self, order_id: str):
        """POST /listings/close"""
        return self._client.close_listing(order_id)

    def send_resource_alert(self, alert: Any):
        """POST /alerts/resource"""
        body = alert.to_dict() if hasattr(alert, "to_dict") else dict(alert)
        return self._client.send_resource_alert(
            event_type=body.get("event_type", "resource_imbalance"),
            resource=body.get("resource", {}),
            value=body.get("value", 0.0),
            label=body.get("label", ""),
            threshold=body.get("threshold", ""),
        )
