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
    
    def _extract_price_from_order(self, order: Dict[str, Any], is_our_order: bool = False) -> tuple[int | None, str | None]:
        """Extract price from an order's TokenResource.
        
        Args:
            order: Order dictionary
            is_our_order: True if this is our order (for determining which resource is the price)
            
        Returns:
            Tuple of (price_amount_in_base_units, token_symbol) or (None, None) if no token resource found
        """
        offer_res = order.get("offer_resource", {})
        demand_res = order.get("demand_resource", {})
        
        # Find the TokenResource (price is always in tokens)
        token_resource = None
        if "token" in offer_res:
            token_resource = offer_res
        elif "token" in demand_res:
            token_resource = demand_res
        
        if not token_resource or "token" not in token_resource:
            return None, None
        
        token_data = token_resource.get("token", {})
        amount = token_resource.get("amount")
        
        if amount is None:
            return None, None
        
        # amount is already in base units (amount * 10**decimals)
        symbol = token_data.get("symbol") if isinstance(token_data, dict) else None
        return int(amount), symbol
    
    def _compare_prices(
        self,
        our_price: int,
        their_price: int,
        epsilon: float = 0.0
    ) -> str:
        """Compare two prices and classify the relationship.
        
        Args:
            our_price: Our price in base units
            their_price: Their price in base units
            epsilon: Tolerance for "equal" classification (as fraction, e.g., 0.01 = 1%)
            
        Returns:
            "equal" | "we_pay_more" | "we_pay_less"
        """
        if epsilon > 0:
            diff_ratio = abs(our_price - their_price) / max(our_price, their_price, 1)
            if diff_ratio <= epsilon:
                return "equal"
        
        if our_price == their_price:
            return "equal"
        elif our_price > their_price:
            return "we_pay_more"
        else:
            return "we_pay_less"
    
    def match_orders(
        self,
        our_order: Dict[str, Any],
        candidate_orders: List[Dict[str, Any]],
        bidirectional: bool = True,
        include_price_analysis: bool = False,
        price_epsilon: float = 0.0
    ) -> List[Dict[str, Any]]:
        """Find matching orders bidirectionally with optional price analysis.
        
        CURRENT BEHAVIOR (Phase 2 - Price-Aware):
        - First pass: Matches orders based on resource type compatibility (compute ↔ token) and direction.
        - Second pass (if include_price_analysis=True): Compares prices and adds price_relation metadata.
        - Price is extracted from TokenResource.amount (base units) in either offer_resource or demand_resource.
        
        Args:
            our_order: Our order dictionary
            candidate_orders: List of candidate orders to match against
            bidirectional: Enable bidirectional matching
            include_price_analysis: If True, add price comparison metadata to results
            price_epsilon: Tolerance for "equal" price classification (fraction, e.g., 0.01 = 1%)
            
        Returns:
            List of matching orders with optional price metadata:
            - If include_price_analysis=False: Returns type-compatible matches only (backward compatible)
            - If include_price_analysis=True: Each match includes:
              - All original order fields
              - "our_price": Our price in base units (int)
              - "their_price": Their price in base units (int)
              - "price_relation": "equal" | "we_pay_more" | "we_pay_less"
        """
        matches = []
        our_offer_type = self._get_resource_type(our_order.get("offer_resource", {}))
        our_demand_type = self._get_resource_type(our_order.get("demand_resource", {}))
        
        # Extract our price once (for price-aware matching)
        our_price, our_token_symbol = self._extract_price_from_order(our_order, is_our_order=True)
        
        for candidate in candidate_orders:
            their_offer_type = self._get_resource_type(candidate.get("offer_resource", {}))
            their_demand_type = self._get_resource_type(candidate.get("demand_resource", {}))
            
            is_type_compatible = False
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
                is_type_compatible = case_a or case_b
            else:
                # Direct match: our offer matches their demand and our demand matches their offer
                is_type_compatible = (our_offer_type == their_demand_type and our_demand_type == their_offer_type)
            
            if not is_type_compatible:
                continue
            
            # Type-compatible match found - add price analysis if requested
            match_result = candidate.copy()  # Don't mutate original
            
            if include_price_analysis:
                their_price, their_token_symbol = self._extract_price_from_order(candidate, is_our_order=False)
                
                if our_price is not None and their_price is not None:
                    # Both orders have token prices - compare them
                    price_relation = self._compare_prices(our_price, their_price, epsilon=price_epsilon)
                    match_result["our_price"] = our_price
                    match_result["their_price"] = their_price
                    match_result["price_relation"] = price_relation
                    match_result["our_token_symbol"] = our_token_symbol
                    match_result["their_token_symbol"] = their_token_symbol
                else:
                    # One or both orders missing price - mark as unknown
                    match_result["our_price"] = our_price
                    match_result["their_price"] = their_price
                    match_result["price_relation"] = "unknown"
                    match_result["our_token_symbol"] = our_token_symbol
                    match_result["their_token_symbol"] = their_token_symbol
            else:
                # Backward compatible: no price metadata
                pass
            
            matches.append(match_result)
        
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

