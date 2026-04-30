from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from market_policy.ports.persistence import NegotiationThreadPersistencePort
from market_policy.identity import Identity

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
            await txn.cancel_competing(order_id, their_listing_id, negotiation_id)

        # Or with custom component name for logging:
        async with NegotiationThreadTransaction("ACCEPT_OFFER") as txn:
            await txn.cancel_competing(order_id, their_listing_id, negotiation_id)
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
            False to propagate the exception (True would suppress it)
        """
        if exc_type:
            logger.error(
                f"[{self.component}] Transaction failed: {exc_val}",
                exc_info=(exc_type, exc_val, exc_tb),
            )
            # Return False to propagate exceptions - failures should be visible
            return False
        return False

    async def cancel_competing(
        self,
        order_id: str | None,
        their_listing_id: str | None,
        except_negotiation_id: str | None,
    ) -> list[dict]:
        """Cancel competing negotiations for both orders.

        Args:
            order_id: Our order ID
            their_listing_id: Their order ID
            except_negotiation_id: Negotiation ID to exclude from cancellation

        Returns:
            List of dicts with negotiation_id, their_listing_id, their_agent_id
            for each canceled negotiation (for sending exit notifications).
        """
        if not self.thread_store:
            logger.warning(f"[{self.component}] No thread store available")
            return []

        seen: set[str] = set()
        all_canceled: list[dict] = []
        for oid in [order_id, their_listing_id]:
            if not oid:
                continue
            canceled = await self.thread_store._sqlite.cancel_negotiations_for_listing(
                order_id=oid,
                except_negotiation_id=except_negotiation_id,
            )
            for entry in canceled:
                neg_id = entry["negotiation_id"]
                if neg_id not in seen:
                    seen.add(neg_id)
                    all_canceled.append(entry)
            if canceled:
                logger.info(
                    f"[{self.component}] Canceled {len(canceled)} competing "
                    f"negotiations for {oid}"
                )
        return all_canceled

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

        active_negotiations = await self.thread_store._sqlite.get_active_negotiations_for_listing(
            order_id=order_id
        )

        active_order_ids = set()
        for neg in active_negotiations:
            if neg["our_listing_id"] == order_id:
                active_order_ids.add(neg["their_listing_id"])
            elif neg["their_listing_id"] == order_id:
                active_order_ids.add(neg["our_listing_id"])

        return active_order_ids

    async def check_duplicate(
        self,
        our_listing_id: str,
        their_listing_id: str,
    ) -> bool:
        """Check if a negotiation already exists between two orders.

        Args:
            our_listing_id: Our order ID
            their_listing_id: Their order ID

        Returns:
            True if negotiation already exists, False otherwise
        """
        if not self.thread_store:
            logger.warning(f"[{self.component}] No thread store available")
            return False

        existing = await self.thread_store._sqlite.check_existing_negotiation(
            our_listing_id=our_listing_id,
            their_listing_id=their_listing_id,
        )
        return existing is not None

    async def mark_terminal(self, negotiation_id: str, state: str) -> None:
        """Mark negotiation as terminal (success/failure/timeout).

        Args:
            negotiation_id: The negotiation to mark as terminal
            state: Terminal state - one of "success", "failure", "timeout"
        """
        if not self.thread_store:
            logger.warning(f"[{self.component}] No thread store available")
            return

        try:
            await self.thread_store._sqlite.update_negotiation_thread_terminal(
                negotiation_id=negotiation_id,
                terminal_state=state,
            )
            logger.info(f"[{self.component}] Marked negotiation {negotiation_id} as {state}")
        except Exception as e:
            logger.error(f"[{self.component}] Failed to mark terminal: {e}")

    async def ensure_thread(
        self,
        negotiation_id: str,
        our_listing_id: str,
        their_listing_id: str,
        our_agent_id: str,
        their_agent_id: str,
        our_initial_price: int | None = None,
        our_strategy: str | None = None,
        requested_duration_seconds: int | None = None,
    ) -> None:
        """Get or create negotiation thread

        Args:
            negotiation_id: Unique ID for this negotiation
            our_listing_id: Our order ID
            their_listing_id: Their order ID
            our_agent_id: Our agent ID
            their_agent_id: Their agent ID
            our_initial_price: Our initial price (floor for maximizer, ceiling for minimizer)
            our_strategy: Our strategy ('minimize' or 'maximize')
            requested_duration_seconds: Buyer's lease ask, recorded on thread creation.
        """
        if not self.thread_store:
            logger.warning(f"[{self.component}] No thread store available")
            return

        # owner_id identifies which agent's private state to access
        owner_id = self.thread_store._identity.agent_url
        existing = await self.thread_store.get_thread_info(
            negotiation_id=negotiation_id,
            owner_id=owner_id,
        )
        if not existing:
            await self.thread_store.create_thread(
                negotiation_id=negotiation_id,
                our_listing_id=our_listing_id,
                their_listing_id=their_listing_id,
                our_agent_id=our_agent_id,
                their_agent_id=their_agent_id,
                owner_id=owner_id,
                our_initial_price=our_initial_price,
                our_strategy=our_strategy,
                requested_duration_seconds=requested_duration_seconds,
            )
            logger.debug(f"[{self.component}] Created thread {negotiation_id}")

    async def add_message(
        self,
        negotiation_id: str,
        sender: str,
        our_price: int | None = None,
        their_price: int | None = None,
        proposed_price: int | None = None,
        action_taken: str = "",
        message_type: str = "",
    ) -> None:
        """Add message to negotiation thread.

        Args:
            negotiation_id: The negotiation thread ID
            sender: Agent ID of sender
            our_price: Our price in this message
            their_price: Their price in this message
            proposed_price: Proposed counter price
            action_taken: Action taken (ACCEPT_OFFER, COUNTER_OFFER, etc.)
            message_type: Type of message (initial_proposal, counter_proposal, etc.)
        """
        if not self.thread_store:
            logger.warning(f"[{self.component}] No thread store available")
            return

        await self.thread_store.add_message(
            negotiation_id=negotiation_id,
            sender=sender,
            our_price=our_price,
            their_price=their_price,
            proposed_price=proposed_price,
            action_taken=action_taken,
            message_type=message_type,
        )


class NegotiationThreadStore:
    """
    SQLite-backed store for negotiation threads.
    
    Implements the corecursive negotiation thread structure from CGT:
    - Thread accumulation: Thread[t] = Thread[t-1] + Message[t]
    - Terminal condition detection
    - Thread history for policy evaluation
    """
    
    def __init__(
        self,
        sqlite_client: NegotiationThreadPersistencePort,
        identity: Identity,
    ):
        """Initialize thread store with persistence client and local identity.

        Args:
            sqlite_client: Persistence client implementing negotiation thread operations.
            identity: Local participant identity. Used as the `owner_id`
                tag on private thread state, and as our_agent_id when
                the engine creates threads for incoming offers.
        """
        self._sqlite = sqlite_client
        self._identity = identity
    
    async def create_thread(
        self,
        negotiation_id: str,
        our_listing_id: str,
        their_listing_id: str,
        our_agent_id: str,
        their_agent_id: str,
        owner_id: str,
        our_initial_price: int | None = None,
        our_strategy: str | None = None,
        requested_duration_seconds: int | None = None,
    ) -> None:
        """Create a new negotiation thread with private local state.

        Args:
            negotiation_id: Unique negotiation identifier
            our_listing_id: Our order ID
            their_listing_id: Their order ID
            our_agent_id: Our agent ID
            their_agent_id: Their agent ID
            owner_id: ID of the agent owning this private state
            our_initial_price: Private initial price
            our_strategy: Private strategy
            requested_duration_seconds: Buyer's lease ask from /negotiate/new.
        """
        await self._sqlite.create_negotiation_thread(
            negotiation_id=negotiation_id,
            our_listing_id=our_listing_id,
            their_listing_id=their_listing_id,
            our_agent_id=our_agent_id,
            their_agent_id=their_agent_id,
            owner_id=owner_id,
            our_initial_price=our_initial_price,
            our_strategy=our_strategy,
            requested_duration_seconds=requested_duration_seconds,
        )
        logger.debug(
            f"[NEGOTIATION THREAD] Created thread {negotiation_id} "
            f"for orders {our_listing_id} <-> {their_listing_id} "
            f"agents {our_agent_id} <-> {their_agent_id}"
        )
    
    async def get_thread_info(
        self,
        negotiation_id: str,
        owner_id: str,
    ) -> Dict[str, Any] | None:
        """Get negotiation thread metadata.
        
        Args:
            negotiation_id: Unique negotiation identifier
            owner_id: ID of the agent requesting the info
            
        Returns:
            Dictionary with thread info including our_initial_price and our_strategy,
            or None if thread doesn't exist.
        """
        return await self._sqlite.get_thread_info(
            negotiation_id=negotiation_id,
            owner_id=owner_id
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
            Round number that was assigned (computed atomically)
        """
        timestamp = datetime.now().isoformat()

        # Let SQLite compute the next round number atomically to avoid race conditions
        round_num = await self._sqlite.save_negotiation_message(
            negotiation_id=negotiation_id,
            round=None,  # Computed atomically in SQLite
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


def get_thread_store(
    sqlite_client: NegotiationThreadPersistencePort | None = None,
    identity: Identity | None = None,
) -> NegotiationThreadStore:
    """Get or create the global negotiation thread store.

    Both `sqlite_client` and `identity` must be provided on the first
    call. Subsequent calls return the cached singleton.

    Args:
        sqlite_client: Persistence client implementation.
        identity: Local participant identity. Stored on the thread
            store and used wherever the engine needs to tag the local
            owner of private state.

    Returns:
        NegotiationThreadStore singleton.
    """
    global _thread_store
    if _thread_store is None:
        if sqlite_client is None or identity is None:
            raise ValueError(
                "Both sqlite_client and identity must be provided on the "
                "first call to get_thread_store()."
            )
        _thread_store = NegotiationThreadStore(sqlite_client, identity)
    return _thread_store
