from __future__ import annotations

import logging
from typing import Any

from core.agent.app.policy.store import PolicyStore
from core.agent.app.schema.pydantic_models import EventType
from core.agent.app.utils.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


class ComputePolicySeeder:
    """Compute-domain policy seeding logic."""

    DEFAULT_POLICY_TRIGGERS = {
        EventType.RESOURCE_IMBALANCE.value,
        EventType.MAKE_OFFER.value,
        EventType.ACCEPT_OFFER.value,
        EventType.RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT.value,
        EventType.ARBITRATION_COMPLETE.value,
        EventType.ORDER_CREATE.value,
        EventType.ORDER_CLOSE.value,
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

        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="make_offer_default_v1",
                trigger_type=EventType.MAKE_OFFER.value,
                callable_ref="make_offer.default.v1",
            )
            await self._sqlite_client.save_policy_composite(
                agent_id=self._agent_id,
                policy_name="make_offer.default.v1",
                components=[
                    "mo.guard.trigger_is_make_offer",
                    "mo.action.torch_arkhai_seller",
                    "mo.action.torch_arkhai_buyer",
                    "mo.action.accept_offer",
                ],
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save make_offer policy: {e}")

        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="accept_offer_default_v1",
                trigger_type=EventType.ACCEPT_OFFER.value,
                callable_ref="ao.action.fulfill_after_accept",
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save accept_offer policy: {e}")

        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="receive_fulfillment_default_v1",
                trigger_type=EventType.RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT.value,
                callable_ref="rcf.action.trust_fulfillment",
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save receive_fulfillment policy: {e}")

        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="arbitration_complete_default_v1",
                trigger_type=EventType.ARBITRATION_COMPLETE.value,
                callable_ref="arb.action.collect_escrow_after_arbitration",
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save arbitration_complete policy: {e}")

    async def ensure_negotiation_policy(self) -> None:
        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="simple_negotiation_random",
                trigger_type=EventType.NEGOTIATION.value,
                callable_ref="simple_negotiation_random",
            )
        except Exception as e:
            logger.warning(f"[POLICY SEED] Failed to save negotiation policy: {e}")

    async def ensure_for_event_type(self, event_type: str | Any) -> None:
        trigger_type = event_type.value if hasattr(event_type, "value") else str(event_type)
        if trigger_type == EventType.NEGOTIATION.value:
            await self.ensure_negotiation_policy()
        elif trigger_type in self.DEFAULT_POLICY_TRIGGERS:
            await self.ensure_default_policies()
