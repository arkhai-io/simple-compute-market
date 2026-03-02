from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from core.agent.app.schema.pydantic_models import Action as DomainAction, DecisionContext
from core.agent.app.ports.persistence import PolicyPersistencePort

from core.agent.app.policy.evaluator import CallableEvaluator

CacheKey = Tuple[str, str]  # (agent_id, trigger_type)


class PolicyStore:
    def __init__(self, sqlite_client: PolicyPersistencePort):
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
