from __future__ import annotations

import logging
from typing import Any

from market_policy.store import PolicyStore
from market_storefront.models.domain_models import EventType
from market_storefront.utils.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


class ComputePolicySeeder:
    """Compute-domain policy seeding.

    After the A2A removal and the buyer-as-client refactor, the surviving
    policy triggers are the *local* events a seller still reacts to via
    `_process_event_with_pipeline`:

        ORDER_CREATE       — POST /listings/create → policy → make_offer
                             action (registry publish, no fan-out)
        ORDER_CLOSE        — POST /listings/close  → policy → close_order
                             action (local + registry unpublish)
        RESOURCE_IMBALANCE — POST /alerts/resource → policy → rebalance
                             (resource poller / reactive rebalance path)

    Everything else (negotiation, settlement, fulfillment, claim) is now
    handled by dedicated sync endpoints (/negotiate/*, /settle/*,
    /orders/{claim,reclaim,refund,arbitrate}) without going through the
    policy engine.
    """

    DEFAULT_POLICY_TRIGGERS = {
        EventType.RESOURCE_IMBALANCE.value,
        EventType.ORDER_CREATE.value,
        EventType.ORDER_CLOSE.value,
        EventType.NEGOTIATION_REQUESTED.value,
    }

    def __init__(self, policy_store: PolicyStore, sqlite_client: SQLiteClient, agent_id: str):
        self._policy_store = policy_store
        self._sqlite_client = sqlite_client
        self._agent_id = agent_id

    async def ensure_default_policies(self) -> None:
        """Ensure default compute-domain policies are saved."""
        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="resource_imbalance_default_v1",
                trigger_type=EventType.RESOURCE_IMBALANCE.value,
                callable_ref="resource_imbalance.default.v1",
            )
            await self._sqlite_client.save_policy_composite(
                agent_id=self._agent_id,
                policy_name="resource_imbalance.default.v1",
                components=[
                    "ri.guard.trigger_is_resource_imbalance",
                    "ri.guard.resource_present",
                    "ri.action.make_offer_from_resource",
                ],
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save resource_imbalance policy: {e}")

        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="order_create_default_v1",
                trigger_type=EventType.ORDER_CREATE.value,
                callable_ref="order_create.default.v1",
            )
            await self._sqlite_client.save_policy_composite(
                agent_id=self._agent_id,
                policy_name="order_create.default.v1",
                components=["oc.action.make_offer_from_order_create"],
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save order_create policy: {e}")

        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="order_close_default_v1",
                trigger_type=EventType.ORDER_CLOSE.value,
                callable_ref="order_close.default.v1",
            )
            await self._sqlite_client.save_policy_composite(
                agent_id=self._agent_id,
                policy_name="order_close.default.v1",
                components=["oc.action.close_order"],
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save order_close policy: {e}")

        # Pre-thread negotiation guard composite. The default for an
        # immediate-deal seller checks inventory match. Operators running
        # non-immediate (futures / off-chain matched) flows replace the
        # composite's components in their seller config so the same
        # /negotiate/new endpoint behaves differently without code changes.
        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="negotiate_request_default_v1",
                trigger_type=EventType.NEGOTIATION_REQUESTED.value,
                callable_ref="negotiate_request.default.v1",
            )
            await self._sqlite_client.save_policy_composite(
                agent_id=self._agent_id,
                policy_name="negotiate_request.default.v1",
                components=[
                    "negotiate.guard.has_matching_inventory",
                    "negotiate.guard.escrow_fields_strict_match",
                ],
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save negotiate_request policy: {e}")

    async def ensure_for_event_type(self, event_type: str | Any) -> None:
        trigger_type = event_type.value if hasattr(event_type, "value") else str(event_type)
        if trigger_type in self.DEFAULT_POLICY_TRIGGERS:
            await self.ensure_default_policies()
