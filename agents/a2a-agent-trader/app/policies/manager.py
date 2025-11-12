from __future__ import annotations

import logging

from app.policies.discovery import discover_and_register
from app.policies.registry import CALLABLE_REGISTRY
from app.policies.sqlite_client import SQLiteClient
from app.policies.store import PolicyStore
from app.schema.pydantic_models import EventType

logger = logging.getLogger(__name__)


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
        sqlite_client: SQLiteClient,
        agent_id: str,
    ):
        """Initialize PolicyManager with dependencies.
        
        Args:
            policy_store: PolicyStore instance for policy operations
            sqlite_client: SQLiteClient instance for database operations
            agent_id: Agent identifier for policy ownership
        """
        self._policy_store = policy_store
        self._sqlite_client = sqlite_client
        self._agent_id = agent_id
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
        discover_and_register("app.policies")
        self._policy_store.register_callables(CALLABLE_REGISTRY)
        self._initialized = True
        logger.info(f"[POLICY MANAGER] Initialized and registered {len(CALLABLE_REGISTRY)} callable policies")

    async def ensure_default_policies(self) -> None:
        """Ensure default policies are saved for resource imbalance and make offer.
        
        Lazy initialization: policies are created on first use.
        """
        try:
            # Resource imbalance policy
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="resource_imbalance_default_v1",
                trigger_type=EventType.RESOURCE_IMBALANCE.value,
                callable_ref="resource_imbalance.default.v1",
            )
            # Persist composite components for resource_imbalance.default.v1
            await self._sqlite_client.save_policy_composite(
                agent_id=self._agent_id,
                policy_name="resource_imbalance.default.v1",
                components=[
                    "ri.guard.trigger_is_resource_imbalance",
                    "ri.guard.resource_present",
                    "ri.action.make_offer_from_resource",
                ],
            )
            logger.debug("[POLICY MANAGER] Ensured resource_imbalance policy")
        except Exception as e:
            logger.warning(f"[POLICY MANAGER] Failed to save resource_imbalance policy: {e}")

        # Make-offer policy (composite saved in DB)
        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="make_offer_default_v1",
                trigger_type=EventType.MAKE_OFFER.value,
                callable_ref="make_offer.default.v1",
            )
            # Persist composite components for make_offer.default.v1
            await self._sqlite_client.save_policy_composite(
                agent_id=self._agent_id,
                policy_name="make_offer.default.v1",
                components=[
                    "mo.guard.trigger_is_make_offer",
                    # "mo.action.accept_offer", # Uncomment this to use the default accept offer policy
                    "mo.action.torch_always_accept_offer", # Uncomment this to use the RPS TorchScript policy
                ],
            )
            logger.debug("[POLICY MANAGER] Ensured make_offer policy")
        except Exception as e:
            logger.warning(f"[POLICY MANAGER] Failed to save make_offer policy: {e}")

    async def ensure_negotiation_policy(self) -> None:
        """Ensure negotiation policy is saved to the store.
        
        Lazy initialization: policy is created on first use.
        """
        try:
            await self._policy_store.save_policy(
                agent_id=self._agent_id,
                policy_name="simple_negotiation_random",
                trigger_type=EventType.NEGOTIATION.value,
                callable_ref="simple_negotiation_random",
            )
            logger.debug("[POLICY MANAGER] Ensured negotiation policy")
        except Exception as e:
            logger.warning(f"[POLICY MANAGER] Failed to save negotiation policy: {e}")

    async def ensure_policy_for_event_type(self, event_type: EventType) -> None:
        """Ensure policy exists for the given event type.
        
        This is a unified method that routes to the appropriate policy
        setup method based on event type.
        
        Args:
            event_type: The event type to ensure policy for
        """
        if event_type == EventType.NEGOTIATION:
            await self.ensure_negotiation_policy()
        elif event_type in (EventType.RESOURCE_IMBALANCE, EventType.MAKE_OFFER):
            await self.ensure_default_policies()
        # Other event types may not have default policies yet
        # This method can be extended as needed

