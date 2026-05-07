"""PolicyService — the agent's policy evaluation and execution core.

Owns the policy infrastructure (PolicyStore, PolicyManager, ComputePolicySeeder)
and exposes named domain-language methods. Domain event construction is
fully private — callers never touch events directly.

Public API
----------
evaluate_create_listing_policy(offer, demand, max_duration, paused) -> str
    Consult the policy about a listing creation. Returns the action_type
    string ("make_offer" | "no_action" | ...). No side effects.

execute_create_listing(offer, demand, max_duration, paused) -> str | None
    Execute a listing creation: SQLite upsert + conditional registry publish.
    Returns listing_id or None.

evaluate_close_listing_policy(listing_id) -> str
    Consult the policy about a listing close. No side effects.

execute_close_listing(listing_id) -> dict
    Execute a listing close: SQLite update + registry update.

evaluate_listing_create_policy_from_raw(offer_raw, demand_raw, max_duration)
    -> PolicyEvaluateResponse
    Dry-run policy evaluation from raw dicts. Used by
    POST /api/v1/system/policy/evaluate. No side effects.

handle_resource_alert(alert_request) -> dict
    Process a ResourceAlertRequest through policy dispatch.
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
from market_storefront.models.domain_models import (
    EventType,  # retained for future callers; not used in evaluate path
    ListingClosedEvent,
    ListingCreatedEvent,
    NegotiationRequestedEvent,
    ResourceAlertRequest,
)
from service.schemas import ActionType as DomainActionType
from market_storefront.models.system_models import PolicyEvaluateResponse
from market_storefront.policy.seeding import ComputePolicySeeder
from market_storefront.utils.action_executor import (
    _sender_id,
    close_order,
    create_order,
    execute_action,
    parse_resource_from_dict,
    publish_order_to_registry,
)
from market_storefront.utils.serializer import serialize_context_for_storage
from market_storefront.utils.sqlite_client import get_sqlite_client
from service.schemas import DecisionContext

logger = logging.getLogger(__name__)


class PolicyService:
    """Stateful singleton — constructed once at lifespan startup."""

    def __init__(self, *, sqlite_client, alkahest_client, config, agent_id: str) -> None:
        self._db = sqlite_client
        self._alkahest = alkahest_client
        self._config = config
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

        base_url = config.base_url_override or ""
        get_thread_store(
            sqlite_client=sqlite_client,
            identity=Identity(agent_url=base_url, agent_id=agent_id),
        )

    # ------------------------------------------------------------------
    # Create listing
    # ------------------------------------------------------------------

    async def evaluate_create_listing_policy(
        self,
        offer: Any,
        demand: Any,
        max_duration_seconds: int | None,
        paused: bool,
    ) -> str:
        """Consult the policy about creating a listing. No side effects.

        Returns the action_type string e.g. "make_offer" | "no_action".
        """
        event = self._build_listing_created_event(offer, demand, max_duration_seconds, paused)
        action = await self._consult_policy(event)
        if not action:
            return "no_action"
        return (
            action.action_type.value
            if hasattr(action.action_type, "value")
            else str(action.action_type)
        )

    async def execute_create_listing(
        self,
        offer: Any,
        demand: Any,
        max_duration_seconds: int | None,
        paused: bool,
    ) -> str | None:
        """Execute listing creation: SQLite upsert + conditional registry publish.

        Returns the listing_id on success, or None if creation failed.
        Records the decision for experience learning.
        """
        event = self._build_listing_created_event(offer, demand, max_duration_seconds, paused)
        action = await self._consult_policy(event)
        if not action:
            logger.warning("[POLICY] No action for create listing event %s", event.event_id)
            return None

        outcome = await execute_action(
            action=action, ctx=None, alkahest_client=self._alkahest
        )
        await self._record_decision(event, action)
        return outcome.get("listing_id")

    # ------------------------------------------------------------------
    # Close listing
    # ------------------------------------------------------------------

    async def evaluate_close_listing_policy(self, listing_id: str) -> str:
        """Consult the policy about closing a listing. No side effects."""
        event = self._build_listing_closed_event(listing_id)
        action = await self._consult_policy(event)
        if not action:
            return "no_action"
        return (
            action.action_type.value
            if hasattr(action.action_type, "value")
            else str(action.action_type)
        )

    async def execute_close_listing(self, listing_id: str) -> dict:
        """Execute listing close: SQLite update + registry update.

        Records the decision for experience learning.
        Returns the close result dict.
        """
        event = self._build_listing_closed_event(listing_id)
        action = await self._consult_policy(event)
        if not action:
            logger.warning("[POLICY] No action for close listing %s", listing_id)
            return {"status": "no_action", "listing_id": listing_id}

        outcome = await execute_action(
            action=action, ctx=None, alkahest_client=self._alkahest
        )
        await self._record_decision(event, action)
        return outcome.get("result", {"status": "closed", "listing_id": listing_id})

    # ------------------------------------------------------------------
    # Pre-thread negotiation guards
    # ------------------------------------------------------------------

    async def consult_pre_negotiation_guards(
        self,
        *,
        listing_id: str,
        listing: dict[str, Any],
        proposed_price: int | None,
        requested_duration_seconds: int | None,
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
            source=self._config.base_url_override or "",
            listing_id=listing_id,
            listing=listing,
            proposed_price=proposed_price,
            requested_duration_seconds=requested_duration_seconds,
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
    # Policy dry-run from raw dicts (for /api/v1/system/policy/evaluate)
    # ------------------------------------------------------------------

    async def evaluate_listing_create_policy_from_raw(
        self,
        offer_raw: dict,
        demand_raw: dict,
        max_duration_seconds: int | None = None,
        policy_components: list[str] | None = None,
    ) -> PolicyEvaluateResponse:
        """Dry-run a listing creation policy evaluation from raw offer/demand dicts.

        Parses resources, builds the event, checks that every component in
        ``policy_components`` is present in ``CALLABLE_REGISTRY``, then runs
        the callable pipeline.  No DB lookup is performed — this is a pure
        data operation.  The caller is responsible for supplying the component
        names (e.g. read from ``GET /api/v1/system/policy`` after seeding).
        """
        from market_policy.registry import CALLABLE_REGISTRY

        if not policy_components:
            return PolicyEvaluateResponse(
                action="no_action",
                policy_used=None,
                components=[],
                resolvable=False,
                reason="policy_components must be provided; supply the callable names to evaluate.",
            )

        try:
            offer_resource = parse_resource_from_dict(offer_raw)
            demand_resource = parse_resource_from_dict(demand_raw)
        except Exception as exc:
            raise ValueError(f"Invalid offer/demand resource: {exc}") from exc

        event = self._build_listing_created_event(
            offer_resource, demand_resource, max_duration_seconds, paused=False
        )

        unresolvable = [c for c in policy_components if c not in CALLABLE_REGISTRY]
        if unresolvable:
            return PolicyEvaluateResponse(
                action="no_action",
                policy_used=None,
                components=policy_components,
                resolvable=False,
                reason=(
                    f"Components not in CALLABLE_REGISTRY: {unresolvable}. "
                    "Call POST /api/v1/admin/policy/seed to discover callables first."
                ),
            )

        action = await self._consult_policy(event)
        if action is None:
            return PolicyEvaluateResponse(
                action="no_action",
                policy_used=None,
                components=policy_components,
                resolvable=len(CALLABLE_REGISTRY) > 0,
                reason=(
                    "Policy evaluated but returned no action. "
                    f"CALLABLE_REGISTRY has {len(CALLABLE_REGISTRY)} entries."
                ),
            )

        action_type = (
            action.action_type.value
            if hasattr(action.action_type, "value")
            else str(action.action_type)
        )
        return PolicyEvaluateResponse(
            action=action_type.lower(),
            policy_used=None,
            components=policy_components,
            resolvable=True,
            reason=None,
        )

    # ------------------------------------------------------------------
    # Resource alert
    # ------------------------------------------------------------------

    async def handle_resource_alert(self, alert_request: ResourceAlertRequest) -> dict:
        """Process a ResourceAlertRequest through policy dispatch."""
        event_id = f"alert_{uuid.uuid4()}"
        try:
            event = alert_request.to_resource_imbalance_event(
                event_id=event_id, source="resource-monitor"
            )
        except Exception as exc:
            raise ValueError(f"Failed to build ResourceImbalanceEvent: {exc}") from exc

        action = await self._consult_policy(event)
        if not action:
            response = alert_request.model_dump(mode="json")
            response["root_agent_response"] = "No policy matched for resource alert."
            return response

        outcome = await execute_action(
            action=action, ctx=None, alkahest_client=self._alkahest
        )
        await self._record_decision(event, action)

        response = alert_request.model_dump(mode="json")
        response["root_agent_response"] = outcome.get("message") or "Alert processed."
        return response

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_listing_created_event(
        self,
        offer: Any,
        demand: Any,
        max_duration_seconds: int | None,
        paused: bool,
    ) -> ListingCreatedEvent:
        base_url = self._config.base_url_override or ""
        return ListingCreatedEvent(
            event_id=f"listing_create_{uuid.uuid4()}",
            source=base_url,
            offer=offer,
            demand=demand,
            max_duration_seconds=max_duration_seconds,
            data={"paused": paused},
        )

    def _build_listing_closed_event(self, listing_id: str) -> ListingClosedEvent:
        base_url = self._config.base_url_override or ""
        return ListingClosedEvent(
            event_id=f"listing_close_{uuid.uuid4()}",
            source=base_url,
            listing_id=listing_id,
        )

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
