from __future__ import annotations

from typing import Callable, Iterable

from app.policies.schema import (
    Action,
    ActionSelection,
    DecisionContext,
    PolicyRule,
    conditions_match,
)


class RuleBasedEvaluator:
    def __init__(self, rules: Iterable[PolicyRule]):
        # Evaluate by priority (desc)
        self.rules = sorted(rules, key=lambda r: r.priority, reverse=True)

    async def evaluate(self, context: DecisionContext) -> Action | None:
        for rule in self.rules:
            if conditions_match(context, rule.conditions):
                sel: ActionSelection = rule.action
                return Action(
                    action_type=sel.action_type,
                    parameters=sel.parameters,
                    confidence=sel.confidence,
                )
        return None


class CallableEvaluator:
    def __init__(self, func: Callable[[DecisionContext], Action | None]):
        self.func = func

    async def evaluate(self, context: DecisionContext) -> Action | None:
        return self.func(context)


class HybridEvaluator:
    def __init__(
        self,
        rule_evaluator: RuleBasedEvaluator | None = None,
        callable_evaluators: list[CallableEvaluator] | None = None,
    ):
        self.rule_evaluator = rule_evaluator
        self.callable_evaluators = callable_evaluators or []

    async def evaluate(self, context: DecisionContext) -> Action | None:
        if self.rule_evaluator is not None:
            action = await self.rule_evaluator.evaluate(context)
            if action is not None:
                return action
        for ce in self.callable_evaluators:
            action = await ce.evaluate(context)
            if action is not None:
                return action
        return None


