"""Negotiation thread storage and management for Strategic Interaction Pattern.

Implements the corecursive negotiation thread structure from CGT:
- Thread accumulation: Thread[t] = Thread[t-1] + Message[t]
- Terminal condition detection
- Thread history for policy evaluation
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
import json

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
    """In-memory store for negotiation threads.
    
    TODO: Migrate to SQLite-backed store for persistence across restarts.
    """
    
    def __init__(self):
        """Initialize thread store."""
        self._threads: Dict[str, List[NegotiationMessage]] = {}
    
    def get_thread(self, negotiation_id: str) -> List[Dict[str, Any]]:
        """Get negotiation thread history.
        
        Args:
            negotiation_id: Unique negotiation identifier
            
        Returns:
            List of message dictionaries (empty list if thread doesn't exist)
        """
        if negotiation_id not in self._threads:
            return []
        
        return [asdict(msg) for msg in self._threads[negotiation_id]]
    
    def add_message(
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
        if negotiation_id not in self._threads:
            self._threads[negotiation_id] = []
        
        round_num = len(self._threads[negotiation_id])
        message = NegotiationMessage(
            round=round_num,
            sender=sender,
            our_price=our_price,
            their_price=their_price,
            proposed_price=proposed_price,
            action_taken=action_taken,
            timestamp=datetime.now().isoformat(),
            message_type=message_type,
        )
        
        self._threads[negotiation_id].append(message)
        logger.debug(f"[NEGOTIATION THREAD] Added message to {negotiation_id}, round {round_num}, action: {action_taken}")
        
        return round_num
    
    def check_terminal(self, negotiation_id: str) -> tuple[bool, str | None]:
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
        if negotiation_id not in self._threads or len(self._threads[negotiation_id]) == 0:
            return False, None
        
        thread = self._threads[negotiation_id]
        
        # Check for EXIT_NEGOTIATION
        if thread[-1].action_taken == "EXIT_NEGOTIATION":
            return True, "timeout"
        
        # Check for ACCEPT-ACCEPT (success)
        if len(thread) >= 2:
            last_two = thread[-2:]
            if (last_two[0].action_taken == "ACCEPT_OFFER" and 
                last_two[1].action_taken == "ACCEPT_OFFER"):
                return True, "success"
        
        # Check for REJECT-REJECT (failure)
        if len(thread) >= 2:
            last_two = thread[-2:]
            if (last_two[0].action_taken == "REJECT_OFFER" and 
                last_two[1].action_taken == "REJECT_OFFER"):
                return True, "failure"
        
        return False, None
    
    def clear_thread(self, negotiation_id: str) -> None:
        """Clear a negotiation thread (after terminal condition reached)."""
        if negotiation_id in self._threads:
            del self._threads[negotiation_id]
            logger.debug(f"[NEGOTIATION THREAD] Cleared thread {negotiation_id}")


# Global thread store instance
_thread_store: Optional[NegotiationThreadStore] = None


def get_thread_store() -> NegotiationThreadStore:
    """Get or create global negotiation thread store."""
    global _thread_store
    if _thread_store is None:
        _thread_store = NegotiationThreadStore()
    return _thread_store

