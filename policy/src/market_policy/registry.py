# Copyright 2025 Google LLC
#
# Lightweight registry for callable policies discovered via decorators.
from __future__ import annotations

import logging
from typing import Callable, Dict
from service.schemas import DomainAction, DecisionContext

logger = logging.getLogger(__name__)

CALLABLE_REGISTRY: Dict[str, Callable[[DecisionContext], DomainAction | None]] = {}


def policy_callable(name: str):
    """Decorator to register a callable policy under a stable name.

    Usage:
        @policy_callable("negotiate.guard.has_matching_inventory")
        def my_guard(ctx: DecisionContext) -> DomainAction | None: ...
    """

    def _wrap(fn: Callable[[DecisionContext], DomainAction | None]):
        if name in CALLABLE_REGISTRY:
            logger.warning("Duplicate policy callable name '%s' will be overwritten", name)
        CALLABLE_REGISTRY[name] = fn
        return fn

    return _wrap

