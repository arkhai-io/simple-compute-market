"""Registry client for discovering agents and querying market orders."""

from __future__ import annotations

import logging
import aiohttp
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from app.utils.config import CONFIG

logger = logging.getLogger(__name__)


class RegistryClient:
    """Client for interacting with the ERC-8004 registry API."""
    
    def __init__(self, base_url: str | None = None, timeout: int = 30):
        """Initialize registry client.
        
        Args:
            base_url: Base URL of the registry API (defaults to CONFIG.indexer_url)
            timeout: Request timeout in seconds
        """
        self.base_url = (base_url or CONFIG.indexer_url).rstrip('/')
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
    
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
            async with session.post(
                f"{self.base_url}/agents/{agent_id}/orders",
                json=order
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
            async with session.put(
                f"{self.base_url}/orders/{order_id}",
                json=updates
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
            async with session.delete(f"{self.base_url}/orders/{order_id}") as response:
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


def get_registry_client() -> RegistryClient:
    """Get or create global registry client instance."""
    global _registry_client
    if _registry_client is None:
        timeout = getattr(CONFIG, 'registry_order_timeout', 30)
        _registry_client = RegistryClient(timeout=timeout)
    return _registry_client

