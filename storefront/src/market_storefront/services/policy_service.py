"""PolicyService — the agent's pre-negotiation guard pipeline.

Holds the policy infrastructure (PolicyStore, PolicyManager,
ComputePolicySeeder) used by the negotiate-request pre-flight guards.
Listing CRUD now bypasses this entirely (see ``ListingService``); the
per-round negotiation strategy is also a separate system (see
``utils/sync_negotiation.py``). The only surviving policy hook
``PolicyService`` serves today is ``consult_pre_negotiation_guards``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from market_policy.identity import Identity
from market_policy.manager import PolicyManager
from market_policy.negotiation_thread import get_thread_store
from market_policy.store import PolicyStore
from market_storefront.models.domain_models import NegotiationRequestedEvent
from service.schemas import ActionType as DomainActionType
from market_storefront.policy.seeding import ComputePolicySeeder
from market_storefront.utils.config import BASE_URL_OVERRIDE
from market_storefront.utils.action_executor import _sender_id
from market_storefront.utils.serializer import serialize_context_for_storage
from service.schemas import DecisionContext

logger = logging.getLogger(__name__)


class PolicyService:
    """Stateful singleton — constructed once at lifespan startup."""

    def __init__(self, *, sqlite_client, alkahest_client, agent_id: str) -> None:
        self._db = sqlite_client
        self._alkahest = alkahest_client
        self._agent_id = agent_id

        self._policy_store = PolicyStore(sqlite_client)
        self._policy_seeder = ComputePolicySeeder(
            policy_store=self._policy_store,
            sqlite_client=sqlite_client,
            agent_id=agent_id,
        )
        self._policy_manager = PolicyManager(
            policy_store=self._policy_store,
            agent_id=agent_id,
            seed_policies_for_event_type=self._policy_seeder.ensure_for_event_type,
        )
        self._policy_manager.initialize()

        base_url = BASE_URL_OVERRIDE or ""
        get_thread_store(
            sqlite_client=sqlite_client,
            identity=Identity(agent_url=base_url, agent_id=agent_id),
        )

    # ------------------------------------------------------------------
    # Pre-thread negotiation guards
    # ------------------------------------------------------------------

    async def consult_pre_negotiation_guards(
        self,
        *,
        listing_id: str,
        listing: dict[str, Any],
        proposed_price: float | None,
        requested_duration_seconds: int | None,
        escrow_proposal: dict[str, Any] | None = None,
    ) -> str | None:
        """Run the seeded negotiate-request policy and return a rejection
        reason on veto, or ``None`` to let the negotiation proceed.

        Called by ``sync_negotiation`` before any thread state mutates.
        The policy composite (default ``negotiate_request.default.v1``)
        chains guard callables; the first one that returns
        ``REJECT_OFFER`` wins, and its ``parameters["reason"]`` becomes
        the rejection reason — translated to HTTP 409
        (``OfferUnfulfillableError``) by the caller.

        Operators who want different gating (e.g. accept all requests
        for a futures-deal flow, or add per-buyer trust checks) edit the
        policy composite's components list — no code changes needed.
        """
        event = NegotiationRequestedEvent(
            event_id=f"negotiate_request_{uuid.uuid4()}",
            source=BASE_URL_OVERRIDE or "",
            listing_id=listing_id,
            listing=listing,
            proposed_price=proposed_price,
            requested_duration_seconds=requested_duration_seconds,
            escrow_proposal=escrow_proposal,
        )
        action = await self._consult_policy(event)
        if action is None:
            return None
        action_type = action.action_type
        action_value = action_type.value if hasattr(action_type, "value") else str(action_type)
        if action_value == DomainActionType.REJECT_OFFER.value:
            reason = (action.parameters or {}).get("reason")
            return str(reason) if reason else "rejected"
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _consult_policy(self, domain_event) -> Any:
        event_type = domain_event.event_type
        await self._policy_manager.ensure_policy_for_event_type(event_type)

        portfolio = await self._db.list_resources()
        past = await self._db.load_recent_decisions(
            agent_id=self._agent_id,
            limit=10,
            event_type=domain_event.event_type.value,
        )
        decision_context = DecisionContext(
            event=domain_event,
            agent_id=_sender_id(),
            available_resources={"resources": portfolio},
            market_state={},
            negotiation_history=[],
            past_experiences=past,
        )
        try:
            return await self._policy_store.evaluate_policy(
                agent_id=self._agent_id,
                context=decision_context,
            )
        except Exception as exc:
            logger.warning("[POLICY] Evaluation failed: %s", exc)
            return None

    async def _record_decision(self, domain_event, action) -> None:
        decision_id = f"dec_{uuid.uuid4()}"
        action_type_str = (
            action.action_type.value
            if hasattr(action.action_type, "value")
            else str(action.action_type)
        )
        try:
            context_json = serialize_context_for_storage(DecisionContext(
                event=domain_event,
                agent_id=_sender_id(),
                available_resources={},
                market_state={},
                negotiation_history=[],
                past_experiences=[],
            ))
            await self._db.save_decision(
                decision_id=decision_id,
                event_id=domain_event.event_id,
                event_type=domain_event.event_type.value,
                agent_id=self._agent_id,
                policy_used=action_type_str,
                action_type=action_type_str,
                timestamp=datetime.now().isoformat(),
                context_json=context_json,
            )
        except Exception as exc:
            logger.error("[POLICY] Failed to record decision: %s", exc)
