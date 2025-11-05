from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from app.policies.evaluator import CallableEvaluator
from app.schema.pydantic_models import Action as DomainAction, DecisionContext
from app.policies.registry import policy_callable
from app.schema.pydantic_models import Action as DomainAction, ActionType as DomainActionType
from app.policies.sqlite_client import SQLiteClient


CacheKey = Tuple[str, str]  # (agent_id, trigger_type)


class PolicyStore:
    def __init__(self, sqlite_client: SQLiteClient):
        self._sqlite = sqlite_client
        self._registry: Dict[str, Callable[[DecisionContext], DomainAction | None]] = {}
        self._cache: Dict[CacheKey, Dict[str, Any]] = {}
        # Composite name -> ordered list of component callable names
        self._composites: Dict[str, List[str]] = {}

    def register_callable(self, name: str, func: Callable[[DecisionContext], DomainAction | None]) -> None:
        self._registry[name] = func

    def register_callables(self, mapping: Dict[str, Callable[[DecisionContext], DomainAction | None]]) -> None:
        for name, func in mapping.items():
            self._registry[name] = func

    def register_composite(self, name: str, components: List[str]) -> None:
        """Record composite chain membership for discovery and auditing."""
        self._composites[name] = list(components)

    def get_composite(self, name: str) -> List[str] | None:
        return self._composites.get(name)

    def list_composites(self) -> Dict[str, List[str]]:
        return dict(self._composites)

    async def save_policy(
        self,
        *,
        agent_id: str,
        policy_name: str,
        trigger_type: str,
        callable_ref: str | None = None,
    ) -> None:
        await self._sqlite.save_policy(
            agent_id=agent_id,
            name=policy_name,
            trigger_type=trigger_type,
            callable_ref=callable_ref,
        )
        # If this references a registered composite, persist its ordered components for SQL queries
        if callable_ref and callable_ref in self._composites:
            try:
                await self._sqlite.save_policy_composite(
                    agent_id=agent_id,
                    policy_name=policy_name,
                    components=self._composites[callable_ref],
                )
            except Exception:
                # Non-fatal; policy remains usable even if composite persistence fails
                pass
        self._cache.pop((agent_id, trigger_type), None)

    async def _load_cached(self, *, agent_id: str, trigger_type: str) -> Dict[str, Any]:
        key = (agent_id, trigger_type)
        if key in self._cache:
            return self._cache[key]
        rows = await self._sqlite.load_policies_by_trigger(agent_id=agent_id, trigger_type=trigger_type)
        callables: List[str] = []
        for row in rows:
            if row.get("callable_ref"):
                callables.append(row["callable_ref"]) 
        data = {"callables": callables}
        self._cache[key] = data
        return data

    async def evaluate_policy(self, *, agent_id: str, context: DecisionContext) -> DomainAction | None:
        # Normalize trigger type to string for storage/lookup consistency
        trigger_type: str
        et = context.event.event_type
        trigger_type = et.value if hasattr(et, "value") else str(et)
        data = await self._load_cached(agent_id=agent_id, trigger_type=trigger_type)
        # Evaluate policies by callable_ref; support composite by expanding from DB
        policy_action: DomainAction | None = None
        for ref in data["callables"]:
            # Direct callable
            if ref in self._registry:
                ce = CallableEvaluator(self._registry[ref])
                policy_action = await ce.evaluate(context)
                if policy_action is not None:
                    break
            # Composite: expand ordered components from DB and execute
            try:
                components = await self._sqlite.load_policy_composite(agent_id=agent_id, policy_name=ref)
            except Exception:
                components = []
            if components:
                for comp in components:
                    func = self._registry.get(comp)
                    if not func:
                        continue
                    ce = CallableEvaluator(func)
                    policy_action = await ce.evaluate(context)
                    if policy_action is not None:
                        break
                if policy_action is not None:
                    break
        return policy_action


# ----- Built-in sample callable policies -----

def simple_negotiation_random(threshold_unused: float | None = None) -> Callable[[DecisionContext], PolicyAction | None]:
    import random
    from app.schema.pydantic_models import ActionType

    def _impl(context: DecisionContext) -> PolicyAction | None:
        # 50/50 accept/reject for offers
        if context.event.event_type != "negotiation":
            return None
        msg_type = context.event.data.get("message_type")
        if msg_type != "offer":
            return None
        choice = random.choice([ActionType.ACCEPT_OFFER, ActionType.REJECT_OFFER])
        return PolicyAction(action_type=choice, parameters={})

    return _impl


def simple_negotiation_callable(gpu_threshold: int = 1) -> Callable[[DecisionContext], PolicyAction | None]:
    from app.schema.pydantic_models import ActionType

    def _impl(context: DecisionContext) -> PolicyAction | None:
        if context.event.event_type != "negotiation":
            return None
        msg_type = context.event.data.get("message_type")
        if msg_type != "offer":
            return None
        total_gpus = int(context.available_resources.get("total_gpus", 0))
        if total_gpus < gpu_threshold:
            return PolicyAction(action_type=ActionType.REJECT_OFFER, parameters={})
        return PolicyAction(action_type=ActionType.ACCEPT_OFFER, parameters={})

    return _impl


# ----- New callable policies to mirror existing hardcoded behavior -----

def resource_imbalance_make_offer() -> Callable[[DecisionContext], PolicyAction | None]:
    from app.schema.pydantic_models import ActionType, ComputeResource

    def _impl(context: DecisionContext) -> PolicyAction | None:
        # Trigger must be resource_imbalance
        et = context.event.event_type
        trigger = et.value if hasattr(et, "value") else str(et)
        if trigger != "resource_imbalance":
            return None
        # Expect a typed ComputeResource on the event; fall back to data mapping if needed
        resource: ComputeResource | None = getattr(context.event, "resource", None)
        if not resource:
            data = context.event.data or {}
            try:
                from app.schema.pydantic_models import GPUModel, Region
                resource = ComputeResource(
                    gpu_model=GPUModel(data.get("gpu_model", "H200")),
                    quantity=int(data.get("quantity", 1)),
                    sla=float(data.get("sla", 90.0)),
                    region=Region(data.get("region", "California, US")),
                )
            except Exception:
                return None
        return PolicyAction(
            action_type=ActionType.MAKE_OFFER,
            parameters={
                "tag": "sell",
                "gpu_model": resource.gpu_model,
                "sla": resource.sla,
                "region": resource.region,
            },
        )

    return _impl


def make_offer_accept_offer() -> Callable[[DecisionContext], PolicyAction | None]:
    from app.schema.pydantic_models import ActionType

    def _impl(context: DecisionContext) -> PolicyAction | None:
        et = context.event.event_type
        trigger = et.value if hasattr(et, "value") else str(et)
        if trigger != "make_offer":
            return None
        return PolicyAction(action_type=ActionType.ACCEPT_OFFER, parameters={})

    return _impl


# ----- Composite chaining support -----

def chain_callables(names: list[str], *, registry: Dict[str, Callable[[DecisionContext], PolicyAction | None]]) -> Callable[[DecisionContext], PolicyAction | None]:
    def _impl(context: DecisionContext) -> PolicyAction | None:
        for name in names:
            func = registry.get(name)
            if not func:
                continue
            act = func(context)
            if act is not None:
                return act
        return None
    return _impl

def build_composite_callable(store: "PolicyStore", name: str, component_names: List[str]) -> Callable[[DecisionContext], PolicyAction | None]:
    """Create a composite callable from registered sub-callables and record its components."""
    store.register_composite(name, component_names)
    return chain_callables(component_names, registry=store._registry)


# ----- Resource imbalance split into sub-callables -----

def ri_validate_and_extract() -> Callable[[DecisionContext], PolicyAction | None]:
    def _impl(context: DecisionContext) -> PolicyAction | None:
        et = context.event.event_type
        trigger = et.value if hasattr(et, "value") else str(et)
        if trigger != "resource_imbalance":
            return None
        # Ensure resource exists
        res = getattr(context.event, "resource", None)
        if not res:
            return None
        # Validation only; continue chain
        return None
    return _impl


def ri_make_offer_from_resource() -> Callable[[DecisionContext], PolicyAction | None]:
    from app.schema.pydantic_models import ActionType

    def _impl(context: DecisionContext) -> PolicyAction | None:
        res = getattr(context.event, "resource", None)
        if not res:
            return None
        return PolicyAction(
            action_type=ActionType.MAKE_OFFER,
            parameters={
                "tag": "sell",
                "gpu_model": res.gpu_model,
                "sla": res.sla,
                "region": res.region,
            },
        )

    return _impl


# ----- Named guard/action callables for versioned composites -----

@policy_callable("ri.guard.trigger_is_resource_imbalance")
def ri_guard_trigger_is_resource_imbalance(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "resource_imbalance":
        return None
    return None


@policy_callable("ri.guard.resource_present")
def ri_guard_resource_present(context: DecisionContext) -> DomainAction | None:
    res = getattr(context.event, "resource", None)
    if not res:
        return None
    return None


@policy_callable("ri.action.make_offer_from_resource")
def ri_action_make_offer_from_resource(context: DecisionContext) -> DomainAction | None:
    from app.schema.pydantic_models import ActionType

    res = getattr(context.event, "resource", None)
    if not res:
        return None
    return DomainAction(
        action_type=ActionType.MAKE_OFFER,
        parameters={
            "tag": "sell",
            "gpu_model": res.gpu_model,
            "sla": res.sla,
            "region": res.region,
        },
    )


@policy_callable("mo.guard.trigger_is_make_offer")
def mo_guard_trigger_is_make_offer(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "make_offer":
        return None
    return None


@policy_callable("mo.action.accept_offer")
def mo_action_accept_offer(context: DecisionContext) -> DomainAction | None:
    from app.schema.pydantic_models import ActionType

    return DomainAction(action_type=ActionType.ACCEPT_OFFER, parameters={})

