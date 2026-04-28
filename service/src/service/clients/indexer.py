"""Registry client for discovering agents and querying market orders."""

from __future__ import annotations

import logging
from dataclasses import dataclass
import aiohttp
from typing import Any, Dict, List, Optional

from service.clients.erc8004.signing import build_order_auth

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CanonicalAgentIdInputs:
    """Inputs needed to build the eip155 canonical agent id used in signing.

    Callers (storefront / buyer) populate this from their own typed
    config instead of having `service.clients.indexer` read env vars.
    """
    onchain_agent_id: str | None = None
    agent_id: str | None = None  # local fallback; used only if no onchain_agent_id
    identity_registry_address: str | None = None
    chain_id: int | None = None
    chain_rpc_url: str | None = None
    alkahest_network: str | None = None  # secondary chain-id source


@dataclass(frozen=True)
class RegistryClientConfig:
    """Everything `RegistryClient` needs at construction time."""
    base_url: str
    timeout: int = 30
    private_key: str | None = None
    agent_id: str | None = None  # canonical eip155:... id


class RegistryClient:
    """Client for interacting with the ERC-8004 registry API."""

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        private_key: str | None = None,
        agent_id: str | None = None,
    ):
        """Initialize registry client.

        All values come from the caller; nothing is read from env.

        Args:
            base_url: Base URL of the registry API
            timeout: Request timeout in seconds
            private_key: Agent private key for signing mutations
            agent_id: Canonical agent ID used as signer_agent_id on updates
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._private_key = private_key
        self._agent_id = agent_id

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def discover_agents(
        self,
        filters: Dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Discover agents from the registry.

        Args:
            filters: Optional filters (q, endpoint_type, trust_model)
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of agent dictionaries
        """
        try:
            session = await self._get_session()
            params = {"limit": limit, "offset": offset}
            if filters:
                params.update(filters)

            async with session.get(f"{self.base_url}/agents", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("items", [])
                else:
                    logger.warning(f"[REGISTRY] Failed to discover agents: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"[REGISTRY] Error discovering agents: {e}")
            return []

    async def get_agent_orders(
        self,
        agent_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get orders for a specific agent.

        Args:
            agent_id: Agent ID
            status: Optional status filter
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of order dictionaries
        """
        try:
            session = await self._get_session()
            params = {"limit": limit, "offset": offset}
            if status:
                params["status"] = status

            async with session.get(f"{self.base_url}/agents/{agent_id}/orders", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("items", [])
                elif response.status == 404:
                    # Agent not found - expected if agent hasn't registered yet
                    logger.debug(f"[REGISTRY] Agent {agent_id} not found in registry (404) - may not be registered yet")
                    return []
                else:
                    logger.warning(f"[REGISTRY] Failed to get agent orders: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"[REGISTRY] Error getting agent orders: {e}")
            return []

    async def get_order(self, order_id: str) -> Dict[str, Any] | None:
        """Get a single order by ID.

        Args:
            order_id: Order ID

        Returns:
            Order dictionary or None if not found or on error
        """
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/orders/{order_id}") as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, dict) and "order" in data and isinstance(data["order"], dict):
                        return data["order"]
                    return data
                if response.status == 404:
                    logger.debug(f"[REGISTRY] Order {order_id} not found in registry (404)")
                    return None
                logger.warning(f"[REGISTRY] Failed to get order {order_id}: {response.status}")
                return None
        except Exception as e:
            logger.error(f"[REGISTRY] Error getting order {order_id}: {e}")
            return None

    async def query_orders(
        self,
        filters: Dict[str, Any] | None = None,
        bidirectional: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Query orders with filters.

        Args:
            filters: Optional filters (offer_resource_type, demand_resource_type, region, gpu_model, sla, status)
            bidirectional: Enable bidirectional matching
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of order dictionaries
        """
        try:
            session = await self._get_session()
            # Convert boolean to string for query params (FastAPI expects string/int/float)
            params = {"limit": limit, "offset": offset, "bidirectional": str(bidirectional).lower()}
            if filters:
                params.update(filters)

            async with session.get(f"{self.base_url}/orders", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("items", [])
                else:
                    logger.warning(f"[REGISTRY] Failed to query orders: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"[REGISTRY] Error querying orders: {e}")
            return []

    async def publish_order(
        self,
        agent_id: str,
        order: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        """Publish an order to the registry.

        Args:
            agent_id: Agent ID
            order: Order dictionary (must include order_id and other MarketOrder fields)

        Returns:
            Published order data or None on error
        """
        try:
            session = await self._get_session()
            payload = dict(order)
            if self._private_key:
                payload.update(build_order_auth(self._private_key, "create_order", agent_id))
            async with session.post(
                f"{self.base_url}/agents/{agent_id}/orders",
                json=payload
            ) as response:
                if response.status == 201:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.warning(f"[REGISTRY] Failed to publish order: {response.status} - {error_text}")
                    return None
        except Exception as e:
            logger.error(f"[REGISTRY] Error publishing order: {e}")
            return None

    async def update_order(
        self,
        order_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        """Update an order in the registry.

        Args:
            order_id: Order ID
            updates: Dictionary of fields to update (status, order_taker, taker_attestation, etc.)

        Returns:
            Updated order data or None on error
        """
        try:
            session = await self._get_session()
            payload = dict(updates)
            if self._private_key and self._agent_id:
                payload.update(build_order_auth(self._private_key, "update_order", order_id))
                payload["signer_agent_id"] = self._agent_id
            async with session.put(
                f"{self.base_url}/orders/{order_id}",
                json=payload
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.warning(f"[REGISTRY] Failed to update order: {response.status} - {error_text}")
                    return None
        except Exception as e:
            logger.error(f"[REGISTRY] Error updating order: {e}")
            return None

    async def delete_order(
        self,
        order_id: str
    ) -> bool:
        """Delete an order from the registry.

        Args:
            order_id: Order ID

        Returns:
            True if successful, False otherwise
        """
        try:
            session = await self._get_session()
            params = {}
            if self._private_key:
                auth = build_order_auth(self._private_key, "delete_order", order_id)
                params = {"signature": auth["signature"], "timestamp": auth["timestamp"]} if auth else {}
            async with session.delete(
                f"{self.base_url}/orders/{order_id}",
                params=params
            ) as response:
                if response.status == 204:
                    return True
                else:
                    error_text = await response.text()
                    logger.warning(f"[REGISTRY] Failed to delete order: {response.status} - {error_text}")
                    return False
        except Exception as e:
            logger.error(f"[REGISTRY] Error deleting order: {e}")
            return False

    def _get_resource_type(self, resource: Dict[str, Any]) -> str:
        """Determine if resource is compute or token."""
        if "token" in resource:
            return "token"
        elif "gpu_model" in resource:
            return "compute"
        return "unknown"

    def match_orders(
        self,
        our_order: Dict[str, Any],
        candidate_orders: List[Dict[str, Any]],
        bidirectional: bool = True
    ) -> List[Dict[str, Any]]:
        """Find matching orders bidirectionally.

        Args:
            our_order: Our order dictionary
            candidate_orders: List of candidate orders to match against
            bidirectional: Enable bidirectional matching

        Returns:
            List of matching orders
        """
        matches = []
        our_offer_type = self._get_resource_type(our_order.get("offer_resource", {}))
        our_demand_type = self._get_resource_type(our_order.get("demand_resource", {}))

        for candidate in candidate_orders:
            their_offer_type = self._get_resource_type(candidate.get("offer_resource", {}))
            their_demand_type = self._get_resource_type(candidate.get("demand_resource", {}))

            if bidirectional:
                # Case A: Our compute offer matches their compute demand AND our token demand matches their token offer
                case_a = (
                    our_offer_type == "compute" and their_demand_type == "compute" and
                    our_demand_type == "token" and their_offer_type == "token"
                )
                # Case B: Our token offer matches their token demand AND our compute demand matches their compute offer
                case_b = (
                    our_offer_type == "token" and their_demand_type == "token" and
                    our_demand_type == "compute" and their_offer_type == "compute"
                )
                if case_a or case_b:
                    matches.append(candidate)
            else:
                # Direct match: our offer matches their demand and our demand matches their offer
                if our_offer_type == their_demand_type and our_demand_type == their_offer_type:
                    matches.append(candidate)

        return matches


# Global registry client instance
_registry_client: Optional[RegistryClient] = None


_ALKAHEST_NETWORK_CHAIN_IDS: dict[str, int] = {
    "anvil": 31337,
    "base_sepolia": 84532,
    "ethereum_sepolia": 11155111,
    "ethereum_mainnet": 1,
}


def resolve_canonical_agent_id(inputs: CanonicalAgentIdInputs) -> str | None:
    """Resolve the full canonical agent ID (eip155:...) for registry signing.

    All inputs come from the caller's typed config; nothing is read
    from env here.

    Resolution order:
    1. ``onchain_agent_id`` already in canonical format → use as-is.
    2. Build from ``onchain_agent_id`` + ``identity_registry_address`` +
       chain ID (taken from ``chain_id``, then the ``alkahest_network``
       lookup, then a web3 call against ``chain_rpc_url``).
    3. Fall back to ``agent_id``.
    """
    onchain_agent_id = inputs.onchain_agent_id
    if not onchain_agent_id:
        return inputs.agent_id

    if onchain_agent_id.startswith("eip155:"):
        return onchain_agent_id

    identity_registry = inputs.identity_registry_address
    if not identity_registry:
        logger.warning(
            "[REGISTRY] identity_registry_address not set; using raw onchain_agent_id=%s as signer_agent_id",
            onchain_agent_id,
        )
        return onchain_agent_id

    try:
        numeric_id = int(onchain_agent_id)
    except ValueError:
        return onchain_agent_id

    # Resolve chain ID from inputs.
    chain_id: int | None = inputs.chain_id
    if chain_id is None and inputs.alkahest_network:
        chain_id = _ALKAHEST_NETWORK_CHAIN_IDS.get(inputs.alkahest_network.lower())
    if chain_id is None and inputs.chain_rpc_url:
        try:
            from web3 import Web3
            from web3.providers import HTTPProvider
            from service.clients.erc8004.blockchain import rpc_url_for_http_provider
            w3 = Web3(HTTPProvider(rpc_url_for_http_provider(inputs.chain_rpc_url), request_kwargs={"timeout": 5}))
            chain_id = w3.eth.chain_id
        except Exception as exc:
            logger.warning("[REGISTRY] Could not resolve chain ID from RPC: %s", exc)
    if chain_id is None:
        logger.warning("[REGISTRY] Cannot resolve chain ID; using raw onchain_agent_id=%s", onchain_agent_id)
        return onchain_agent_id

    try:
        from service.clients.erc8004.blockchain import build_erc8004_canonical_id
        canonical = build_erc8004_canonical_id(chain_id, identity_registry, numeric_id)
        logger.debug("[REGISTRY] Resolved canonical agent ID: %s", canonical)
        return canonical
    except Exception as exc:
        logger.warning("[REGISTRY] Failed to build canonical ID: %s", exc)
        return onchain_agent_id


# Stored config for the global singleton. Set once at startup via
# ``configure_registry_client``; ``get_registry_client`` then constructs
# (or reuses) the singleton from it.
_registry_client_config: Optional[RegistryClientConfig] = None


def configure_registry_client(config: RegistryClientConfig) -> None:
    """Bind the global ``RegistryClient`` to a typed config.

    Called once at process startup (storefront agent.py / buyer CLI /
    register_onchain script) before any code path invokes
    ``get_registry_client()``. Replaces the prior env-driven init.
    """
    global _registry_client_config, _registry_client
    _registry_client_config = config
    _registry_client = None  # force rebuild on next get


def get_registry_client() -> RegistryClient:
    """Return the global registry client.

    Requires ``configure_registry_client`` to have been called first;
    raises if the runtime forgot to wire its config.
    """
    global _registry_client
    if _registry_client is None:
        if _registry_client_config is None:
            raise RuntimeError(
                "RegistryClient is not configured. Call "
                "configure_registry_client(...) at startup before any "
                "code path that needs a registry client."
            )
        _registry_client = RegistryClient(
            base_url=_registry_client_config.base_url,
            timeout=_registry_client_config.timeout,
            private_key=_registry_client_config.private_key,
            agent_id=_registry_client_config.agent_id,
        )
    return _registry_client
