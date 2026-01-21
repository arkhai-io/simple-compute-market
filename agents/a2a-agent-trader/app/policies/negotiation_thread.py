from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

from app.policies.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


@dataclass
class NegotiationMessage:
    """A single message in a negotiation thread."""
    round: int
    sender: str
    our_price: int | None
    their_price: int | None
    proposed_price: int | None
    action_taken: str  # ACCEPT_OFFER, REJECT_OFFER, COUNTER_OFFER, EXIT_NEGOTIATION
    timestamp: str
    message_type: str  # initial_proposal, counter_proposal, etc.


class NegotiationThreadStore:
    """
    SQLite-backed store for negotiation threads.
    
    Implements the corecursive negotiation thread structure from CGT:
    - Thread accumulation: Thread[t] = Thread[t-1] + Message[t]
    - Terminal condition detection
    - Thread history for policy evaluation
    """
    
    def __init__(self, sqlite_client: SQLiteClient):
        """Initialize thread store with SQLite client.
        
        Args:
            sqlite_client: SQLiteClient instance for database operations
        """
        self._sqlite = sqlite_client
    
    async def create_thread(
        self,
        negotiation_id: str,
        our_order_id: str,
        their_order_id: str,
        our_agent_id: str,
        their_agent_id: str,
    ) -> None:
        """Create a new negotiation thread with order and agent tracking."""
        await self._sqlite.create_negotiation_thread(
            negotiation_id=negotiation_id,
            our_order_id=our_order_id,
            their_order_id=their_order_id,
            our_agent_id=our_agent_id,
            their_agent_id=their_agent_id,
        )
        logger.debug(
            f"[NEGOTIATION THREAD] Created thread {negotiation_id} "
            f"for orders {our_order_id} <-> {their_order_id} "
            f"agents {our_agent_id} <-> {their_agent_id}"
        )
    
    async def get_thread(self, negotiation_id: str) -> List[Dict[str, Any]]:
        """Get negotiation thread history.
        
        Args:
            negotiation_id: Unique negotiation identifier
            
        Returns:
            List of message dictionaries (empty list if thread doesn't exist)
        """
        return await self._sqlite.load_negotiation_thread(negotiation_id=negotiation_id)
    
    async def add_message(
        self,
        negotiation_id: str,
        sender: str,
        our_price: int | None,
        their_price: int | None,
        proposed_price: int | None,
        action_taken: str,
        message_type: str = "proposal",
    ) -> int:
        """Add a message to the negotiation thread.
        
        Args:
            negotiation_id: Unique negotiation identifier
            sender: Agent ID or card URL of the sender
            our_price: Our price in base units
            their_price: Their price in base units
            proposed_price: Proposed counter price (if action is COUNTER_OFFER)
            action_taken: Action taken (ACCEPT_OFFER, REJECT_OFFER, COUNTER_OFFER, EXIT_NEGOTIATION)
            message_type: Type of message (initial_proposal, counter_proposal, etc.)
            
        Returns:
            Round number (0-indexed)
        """
        # Load existing thread to determine next round number
        existing_thread = await self.get_thread(negotiation_id)
        round_num = len(existing_thread)
        
        timestamp = datetime.now().isoformat()
        
        await self._sqlite.save_negotiation_message(
            negotiation_id=negotiation_id,
            round=round_num,
            sender=sender,
            our_price=our_price,
            their_price=their_price,
            proposed_price=proposed_price,
            action_taken=action_taken,
            message_type=message_type,
            timestamp=timestamp,
        )
        
        logger.debug(f"[NEGOTIATION THREAD] Added message to {negotiation_id}, round {round_num}, action: {action_taken}")
        
        return round_num
    
    async def check_terminal(self, negotiation_id: str) -> tuple[bool, str | None]:
        """Check if negotiation has reached a terminal condition.
        
        Terminal conditions:
        - Both parties ACCEPT_OFFER (success)
        - Both parties REJECT_OFFER (failure)
        - EXIT_NEGOTIATION (forced termination)
        
        Args:
            negotiation_id: Unique negotiation identifier
            
        Returns:
            Tuple of (is_terminal, terminal_state)
            terminal_state: "success" | "failure" | "timeout" | None
        """
        thread = await self.get_thread(negotiation_id)
        
        if len(thread) == 0:
            return False, None
        
        # Check for EXIT_NEGOTIATION
        if thread[-1]["action_taken"] == "EXIT_NEGOTIATION":
            await self._sqlite.update_negotiation_thread_terminal(
                negotiation_id=negotiation_id,
                terminal_state="timeout",
            )
            return True, "timeout"
        
        # Check for ACCEPT-ACCEPT (success)
        if len(thread) >= 2:
            last_two = thread[-2:]
            if (last_two[0]["action_taken"] == "ACCEPT_OFFER" and 
                last_two[1]["action_taken"] == "ACCEPT_OFFER"):
                await self._sqlite.update_negotiation_thread_terminal(
                    negotiation_id=negotiation_id,
                    terminal_state="success",
                )
                return True, "success"
        
        # Check for REJECT-REJECT (failure)
        if len(thread) >= 2:
            last_two = thread[-2:]
            if (last_two[0]["action_taken"] == "REJECT_OFFER" and 
                last_two[1]["action_taken"] == "REJECT_OFFER"):
                await self._sqlite.update_negotiation_thread_terminal(
                    negotiation_id=negotiation_id,
                    terminal_state="failure",
                )
                return True, "failure"
        
        return False, None
    
    async def clear_thread(self, negotiation_id: str) -> None:
        """Clear a negotiation thread (after terminal condition reached)."""
        await self._sqlite.delete_negotiation_thread(negotiation_id=negotiation_id)
        logger.debug(f"[NEGOTIATION THREAD] Cleared thread {negotiation_id}")


# Global thread store instance (will be initialized by agent)
_thread_store: Optional[NegotiationThreadStore] = None


def get_thread_store(sqlite_client: SQLiteClient | None = None) -> NegotiationThreadStore:
    """Get or create global negotiation thread store.
    
    Args:
        sqlite_client: SQLiteClient instance. If None, uses the global instance.
                      Must be provided on first call.
    
    Returns:
        NegotiationThreadStore instance
    """
    global _thread_store
    if _thread_store is None:
        if sqlite_client is None:
            raise ValueError(
                "SQLiteClient must be provided on first call to get_thread_store(). "
                "Call from agent initialization with sqlite_client parameter."
            )
        _thread_store = NegotiationThreadStore(sqlite_client)
    return _thread_store

