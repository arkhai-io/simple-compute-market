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


class NegotiationThreadTransaction:
    """Context manager for transactional negotiation operations.

    This context manager provides clean error handling and transactional semantics
    for negotiation database operations. It automatically handles exceptions and
    logs errors consistently.

    Example usage:
        async with NegotiationThreadTransaction() as txn:
            await txn.cancel_competing(order_id, their_order_id, negotiation_id)

        # Or with custom component name for logging:
        async with NegotiationThreadTransaction("ACCEPT_OFFER") as txn:
            await txn.cancel_competing(order_id, their_order_id, negotiation_id)
    """

    def __init__(self, component: str = "NEGOTIATION"):
        """Initialize transaction context manager.

        Args:
            component: Component name for logging (e.g., "NEGOTIATION", "ACCEPT_OFFER")
        """
        self.component = component
        self.thread_store = None

    async def __aenter__(self):
        """Enter context manager and get thread store."""
        self.thread_store = get_thread_store()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager and handle any exceptions.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred

        Returns:
            True to suppress the exception, False to propagate it
        """
        if exc_type:
            logger.warning(f"[{self.component}] Transaction failed: {exc_val}")
            return True  # Suppress exception
        return False

    async def cancel_competing(
        self,
        order_id: str | None,
        their_order_id: str | None,
        except_negotiation_id: str | None,
    ) -> None:
        """Cancel competing negotiations for both orders.

        Args:
            order_id: Our order ID
            their_order_id: Their order ID
            except_negotiation_id: Negotiation ID to exclude from cancellation
        """
        if not self.thread_store:
            logger.warning(f"[{self.component}] No thread store available")
            return

        for oid in [order_id, their_order_id]:
            if not oid:
                continue
            canceled = await self.thread_store._sqlite.cancel_negotiations_for_order(
                order_id=oid,
                except_negotiation_id=except_negotiation_id,
            )
            if canceled:
                logger.info(
                    f"[{self.component}] Canceled {len(canceled)} competing "
                    f"negotiations for {oid}"
                )

    async def filter_active(self, order_id: str) -> set[str]:
        """Get set of order IDs already in active negotiations.

        Args:
            order_id: Our order ID

        Returns:
            Set of order IDs currently in active negotiations with our order
        """
        if not self.thread_store:
            logger.warning(f"[{self.component}] No thread store available")
            return set()

        active_negotiations = await self.thread_store._sqlite.get_active_negotiations_for_order(
            order_id=order_id
        )

        active_order_ids = set()
        for neg in active_negotiations:
            if neg["our_order_id"] == order_id:
                active_order_ids.add(neg["their_order_id"])
            elif neg["their_order_id"] == order_id:
                active_order_ids.add(neg["our_order_id"])

        return active_order_ids

    async def check_duplicate(
        self,
        our_order_id: str,
        their_order_id: str,
    ) -> bool:
        """Check if a negotiation already exists between two orders.

        Args:
            our_order_id: Our order ID
            their_order_id: Their order ID

        Returns:
            True if negotiation already exists, False otherwise
        """
        if not self.thread_store:
            logger.warning(f"[{self.component}] No thread store available")
            return False

        existing = await self.thread_store._sqlite.check_existing_negotiation(
            our_order_id=our_order_id,
            their_order_id=their_order_id,
        )
        return existing is not None


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
        """Check if negotiation has reached a terminal condition using pattern matching.

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

        if not thread:
            return False, None

        # Single-action terminals
        match thread[-1]["action_taken"]:
            case "EXIT_NEGOTIATION":
                return await self._mark_terminal(negotiation_id, "timeout")

        # Two-action terminals
        if len(thread) >= 2:
            last_two = (thread[-2]["action_taken"], thread[-1]["action_taken"])
            match last_two:
                case ("ACCEPT_OFFER", "ACCEPT_OFFER"):
                    return await self._mark_terminal(negotiation_id, "success")
                case ("REJECT_OFFER", "REJECT_OFFER"):
                    return await self._mark_terminal(negotiation_id, "failure")

        return False, None

    async def _mark_terminal(self, negotiation_id: str, state: str) -> tuple[bool, str]:
        """Helper to mark thread as terminal and return result.

        Args:
            negotiation_id: Unique negotiation identifier
            state: Terminal state ("success" | "failure" | "timeout")

        Returns:
            Tuple of (True, state)
        """
        await self._sqlite.update_negotiation_thread_terminal(
            negotiation_id=negotiation_id,
            terminal_state=state,
        )
        return True, state
    
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

