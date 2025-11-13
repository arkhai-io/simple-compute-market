from __future__ import annotations

from typing import Callable

from app.schema.pydantic_models import Action, DecisionContext


class CallableEvaluator:
    def __init__(self, func: Callable[[DecisionContext], Action | None]):
        self.func = func

    async def evaluate(self, context: DecisionContext) -> Action | None:
        return self.func(context)

