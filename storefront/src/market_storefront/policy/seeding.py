from __future__ import annotations

import logging
from typing import Any

from market_policy.store import PolicyStore
from market_storefront.models.domain_models import EventType
from market_storefront.utils.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


class ComputePolicySeeder:
    """Compute-domain policy seeding.

    Only one policy hook survives in this refactor pass: the pre-thread
    negotiation guard composite that runs at ``POST /negotiate/new``
    before any thread state mutates. Listing CRUD, lease lifecycle, and
    settlement all go through procedural endpoints (no policy layer).
    Per-round negotiation decisions use ``NegotiationStrategy`` directly.
    """

    DEFAULT_POLICY_TRIGGERS = {
        EventType.NEGOTIATION_REQUESTED.value,
    }

    def __init__(self, policy_store: PolicyStore, sqlite_client: SQLiteClient, agent_id: str):
        self._policy_store = policy_store
        self._sqlite_client = sqlite_client
        self._agent_id = agent_id

    async def ensure_default_policies(self) -> None:
        """Ensure default negotiate-request guard composite is saved.

        Operators running non-immediate (futures / off-chain matched) flows
        replace the composite's components in their seller config so the
        same /negotiate/new endpoint behaves differently without code changes.
        """
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
