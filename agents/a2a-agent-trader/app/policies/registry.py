# Copyright 2025 Google LLC
#
# Lightweight registry for callable policies discovered via decorators.
from __future__ import annotations

import logging
from typing import Callable, Dict

from app.policies.schema import Action as PolicyAction, DecisionContext

logger = logging.getLogger(__name__)

CALLABLE_REGISTRY: Dict[str, Callable[[DecisionContext], PolicyAction | None]] = {}


def policy_callable(name: str):
    """Decorator to register a callable policy under a stable name.

    Usage:
        @policy_callable("ri.guard.trigger_is_resource_imbalance")
        def my_guard(ctx: DecisionContext) -> PolicyAction | None: ...
    """

    def _wrap(fn: Callable[[DecisionContext], PolicyAction | None]):
        if name in CALLABLE_REGISTRY:
            logger.warning("Duplicate policy callable name '%s' will be overwritten", name)
        CALLABLE_REGISTRY[name] = fn
        return fn

    return _wrap
