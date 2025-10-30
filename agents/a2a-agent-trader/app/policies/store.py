from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from app.policies.evaluator import CallableEvaluator, HybridEvaluator, RuleBasedEvaluator
from app.policies.schema import Action, DecisionContext, PolicyRule
from app.policies.sqlite_client import SQLiteClient


CacheKey = Tuple[str, str]  # (agent_id, trigger_type)


class PolicyStore:
    def __init__(self, sqlite_client: SQLiteClient):
        self._sqlite = sqlite_client
        self._registry: Dict[str, Callable[[DecisionContext], Action | None]] = {}
        self._cache: Dict[CacheKey, Dict[str, Any]] = {}

    def register_callable(self, name: str, func: Callable[[DecisionContext], Action | None]) -> None:
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

    async def evaluate_policy(self, *, agent_id: str, context: DecisionContext) -> Action | None:
        data = await self._load_cached(agent_id=agent_id, trigger_type=context.event.event_type)
        rule_eval = RuleBasedEvaluator(data["rules"]) if data["rules"] else None
        callable_evals = [CallableEvaluator(self._registry[name]) for name in data["callables"] if name in self._registry]
        hybrid = HybridEvaluator(rule_evaluator=rule_eval, callable_evaluators=callable_evals)
        return await hybrid.evaluate(context)


# ----- Built-in sample callable policies -----

def simple_negotiation_random(threshold_unused: float | None = None) -> Callable[[DecisionContext], Action | None]:
    import random
    from app.policies.schema import ActionType

    def _impl(context: DecisionContext) -> Action | None:
        # 50/50 accept/reject for offers
        if context.event.event_type != "negotiation":
            return None
        msg_type = context.event.data.get("message_type")
        if msg_type != "offer":
            return None
        choice = random.choice([ActionType.ACCEPT_OFFER, ActionType.REJECT_OFFER])
        return Action(action_type=choice, parameters={})

    return _impl


def simple_negotiation_callable(gpu_threshold: int = 1) -> Callable[[DecisionContext], Action | None]:
    from app.policies.schema import ActionType

    def _impl(context: DecisionContext) -> Action | None:
        if context.event.event_type != "negotiation":
            return None
        msg_type = context.event.data.get("message_type")
        if msg_type != "offer":
            return None
        total_gpus = int(context.available_resources.get("total_gpus", 0))
        if total_gpus < gpu_threshold:
            return Action(action_type=ActionType.REJECT_OFFER, parameters={})
        return Action(action_type=ActionType.ACCEPT_OFFER, parameters={})

    return _impl


