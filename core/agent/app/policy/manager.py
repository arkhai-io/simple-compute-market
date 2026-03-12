from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from core.agent.app.policy.discovery import discover_and_register
from core.agent.app.policy.registry import CALLABLE_REGISTRY
from core.agent.app.policy.store import PolicyStore

logger = logging.getLogger(__name__)

PolicySeeder = Callable[[str | Any], Awaitable[None]]


class PolicyManager:
    """Manages policy discovery, registration, and lazy initialization.
    
    Handles the lifecycle of policies including:
    - Discovery and registration of callable policies
    - Lazy setup of default policies when needed
    - Policy configuration management
    """

    def __init__(
        self,
        policy_store: PolicyStore,
        agent_id: str,
        seed_policies_for_event_type: PolicySeeder | None = None,
    ):
        """Initialize PolicyManager with dependencies.
        
        Args:
            policy_store: PolicyStore instance for policy operations
            agent_id: Agent identifier for policy ownership
            seed_policies_for_event_type: Optional domain-specific policy seeder callback
        """
        self._policy_store = policy_store
        self._agent_id = agent_id
        self._seed_policies_for_event_type = seed_policies_for_event_type
        self._initialized = False

    def initialize(self) -> None:
        """Run policy discovery and register callables.
        
        This should be called once at agent startup to discover and register
        all callable policies decorated with @policy_callable.
        """
        if self._initialized:
            logger.debug("PolicyManager already initialized, skipping")
            return

        # Auto-discover and bulk-register callable policies
        discover_and_register("core.agent.app.policy")
        discover_and_register("domain.compute.agent.app.policy")
        self._policy_store.register_callables(CALLABLE_REGISTRY)
        self._initialized = True
        logger.info(f"[POLICY MANAGER] Initialized and registered {len(CALLABLE_REGISTRY)} callable policies")

    async def ensure_policy_for_event_type(self, event_type: str | Any) -> None:
        """Delegate policy seeding for an event type to the configured domain callback."""
        if not self._seed_policies_for_event_type:
            return
        await self._seed_policies_for_event_type(event_type)
