from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from app.policies.evaluator import CallableEvaluator, HybridEvaluator, RuleBasedEvaluator
from app.policies.schema import Action as PolicyAction, DecisionContext, PolicyRule
from app.schema.pydantic_models import Action as DomainAction, ActionType as DomainActionType
from app.policies.sqlite_client import SQLiteClient


CacheKey = Tuple[str, str]  # (agent_id, trigger_type)


class PolicyStore:
    def __init__(self, sqlite_client: SQLiteClient):
        self._sqlite = sqlite_client
        self._registry: Dict[str, Callable[[DecisionContext], PolicyAction | None]] = {}
        self._cache: Dict[CacheKey, Dict[str, Any]] = {}

    def register_callable(self, name: str, func: Callable[[DecisionContext], PolicyAction | None]) -> None:
        self._registry[name] = func

    async def save_policy(
        self,
        *,
        agent_id: str,
        policy_name: str,
        trigger_type: str,
        rule: PolicyRule | None = None,
        callable_ref: str | None = None,
    ) -> None:
        priority = rule.priority if rule else 0
        rule_json = rule.model_dump_json() if rule else None
        await self._sqlite.save_policy(
            agent_id=agent_id,
            name=policy_name,
            trigger_type=trigger_type,
            rule_json=rule_json,
            callable_ref=callable_ref,
            priority=priority,
        )
        self._cache.pop((agent_id, trigger_type), None)

    async def _load_cached(self, *, agent_id: str, trigger_type: str) -> Dict[str, Any]:
        key = (agent_id, trigger_type)
        if key in self._cache:
            return self._cache[key]
        rows = await self._sqlite.load_policies_by_trigger(agent_id=agent_id, trigger_type=trigger_type)
        rules: List[PolicyRule] = []
        callables: List[str] = []
        for row in rows:
            if row.get("rule_json"):
                try:
                    rules.append(PolicyRule.model_validate_json(row["rule_json"]))
                except Exception:
                    continue
            if row.get("callable_ref"):
                callables.append(row["callable_ref"]) 
        # sort rules by priority desc
        rules.sort(key=lambda r: r.priority, reverse=True)
        data = {"rules": rules, "callables": callables}
        self._cache[key] = data
        return data

    async def evaluate_policy(self, *, agent_id: str, context: DecisionContext) -> DomainAction | None:
        # Normalize trigger type to string for storage/lookup consistency
        trigger_type: str
        et = context.event.event_type
        trigger_type = et.value if hasattr(et, "value") else str(et)
        data = await self._load_cached(agent_id=agent_id, trigger_type=trigger_type)
        rule_eval = RuleBasedEvaluator(data["rules"]) if data["rules"] else None
        callable_evals = [CallableEvaluator(self._registry[name]) for name in data["callables"] if name in self._registry]
        hybrid = HybridEvaluator(rule_evaluator=rule_eval, callable_evaluators=callable_evals)
        policy_action = await hybrid.evaluate(context)
        if policy_action is None:
            return None
        # Convert PolicyAction (policies.schema.Action) -> DomainAction (pydantic Action)
        at = policy_action.action_type
        action_type = (
            at if isinstance(at, DomainActionType) else DomainActionType(str(at))
        )
        return DomainAction(action_type=action_type, parameters=policy_action.parameters)


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

