from __future__ import annotations

import asyncio
from typing import Callable

from core.agent.app.schema.pydantic_models import Action, DecisionContext


class CallableEvaluator:
    def __init__(self, func: Callable[[DecisionContext], Action | None]):
        self.func = func

    async def evaluate(self, context: DecisionContext) -> Action | None:
        result = self.func(context)
        # Handle async policy callables (e.g., negotiation_respond_to_make_offer)
        if asyncio.iscoroutine(result):
            return await result
        return result

