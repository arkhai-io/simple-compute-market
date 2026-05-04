"""PolicyPipelineService — the agent's reactive decision-making core.

Owns the policy infrastructure and the reactive event pipeline:
  - PolicyStore / PolicyManager / ComputePolicySeeder lifecycle
  - NegotiationThreadStore initialization
  - process_event()         — run any DomainEvent through the pipeline
  - handle_resource_alert() — convert ResourceAlertRequest → pipeline
  - pop_outcome()           — retrieve the last action outcome by event_id

This is the agent brain: it decides what to do in response to domain
events. Listing CRUD lives in ListingService; health/status live in
SystemService. Dependencies injected at construction time.
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
from market_storefront.models.domain_models import ResourceAlertRequest
from market_storefront.policy.seeding import ComputePolicySeeder
from market_storefront.utils.action_executor import _sender_id, execute_action
from market_storefront.utils.event_ingestion import is_event_queue_enabled, queue_event
from market_storefront.utils.serializer import serialize_context_for_storage
from service.schemas import DecisionContext

logger = logging.getLogger(__name__)


class PolicyPipelineService:
    """Stateful singleton — constructed once at lifespan startup."""

    def __init__(self, *, sqlite_client, alkahest_client, config, agent_id: str) -> None:
        self._db = sqlite_client
        self._alkahest = alkahest_client
        self._config = config
        self._agent_id = agent_id
        self._last_action_outcomes: dict[str, dict] = {}

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

        base_url = config.base_url_override or ""
        get_thread_store(
            sqlite_client=sqlite_client,
            identity=Identity(agent_url=base_url, agent_id=agent_id),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pop_outcome(self, event_id: str) -> dict | None:
        """Retrieve and remove the action outcome for a completed pipeline run."""
        return self._last_action_outcomes.pop(event_id, None)

    async def process_event(self, domain_event) -> str:
        """Run a DomainEvent through the full reactive pipeline.

        Returns a human-readable outcome message string.
        Stores the action outcome dict in _last_action_outcomes[event_id]
        so callers can retrieve it via pop_outcome().
        """
        action = await self._consult_policy(domain_event)
        if not action:
            logger.warning("[PIPELINE] No action for event %s", domain_event.event_id)
            return "NO ACTION. No policy matched."

        # Build decision record for experience logging
        decision_id = f"dec_{uuid.uuid4()}"
        policy_used = (
            action.action_type.value
            if hasattr(action.action_type, "value")
            else str(action.action_type)
        )

        outcome = await execute_action(
            action=action, ctx=None, alkahest_client=self._alkahest
        )
        self._last_action_outcomes[domain_event.event_id] = outcome

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
                policy_used=policy_used,
                action_type=policy_used,
                timestamp=__import__("datetime").datetime.now().isoformat(),
                context_json=context_json,
            )
        except Exception as exc:
            logger.error("[PIPELINE] Failed to record decision: %s", exc)

        outcome_message = outcome.get("message")
        action_labels = {
            "accept_offer": "ACCEPT the offer.",
            "reject_offer": "REJECT the offer.",
            "counter_offer": "COUNTER the offer.",
            "make_offer": "MAKE OFFER. Create market listing.",
            "resolve_internally": "RESOLVE INTERNALLY.",
            "collect_escrow": "COLLECT ESCROW.",
            "noop": "NOOP.",
        }
        fallback = action_labels.get(policy_used.lower(), "Action executed.")
        return outcome_message or fallback

    async def handle_resource_alert(self, alert_request: ResourceAlertRequest) -> dict:
        """Process a validated ResourceAlertRequest through the reactive pipeline."""
        event_id = f"alert_{uuid.uuid4()}"
        try:
            event = alert_request.to_resource_imbalance_event(
                event_id=event_id, source="resource-monitor"
            )
        except Exception as exc:
            raise ValueError(f"Failed to build ResourceImbalanceEvent: {exc}") from exc

        if is_event_queue_enabled():
            queue_event(event.model_dump(mode="json"))
            result = alert_request.model_dump(mode="json")
            result["root_agent_response"] = "Alert processing queued."
            return result

        response_text = await self.process_event(event)
        result = alert_request.model_dump(mode="json")
        result["root_agent_response"] = response_text or "Alert processed."
        return result

    # ------------------------------------------------------------------
    # Internal helpers
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
            action = await self._policy_store.evaluate_policy(
                agent_id=self._agent_id,
                context=decision_context,
            )
            return action
        except Exception as exc:
            logger.warning("[PIPELINE] Policy evaluation failed: %s", exc)
            return None
