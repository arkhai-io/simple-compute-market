"""Action builders for creating DomainAction objects with consistent parameter structure.

This module provides builder classes that simplify the creation of DomainAction objects
throughout the policy system. Instead of manually constructing DomainAction objects
with repeated parameter extraction logic, policies can use these builders for cleaner,
more maintainable code.
"""

from dataclasses import dataclass
from typing import Any
import logging

from app.schema.pydantic_models import Action as DomainAction, ActionType

logger = logging.getLogger(__name__)


@dataclass
class NegotiationActionBuilder:
    """Builder for negotiation-related actions.

    This builder provides a clean interface for creating negotiation actions
    without repetitive parameter extraction and DomainAction construction.

    Example usage:
        data = context.event.data or {}
        actions = NegotiationActionBuilder(data)

        # Simple, readable action creation
        if our_price == their_price:
            return actions.accept("price_equal")

        if price_too_far:
            return actions.exit("price_unreasonable")

        return actions.counter(proposed_price)
    """

    data: dict[str, Any]

    def accept(self, reason: str) -> DomainAction:
        """Build ACCEPT_OFFER action.

        Args:
            reason: Human-readable reason for accepting (e.g., "within_band", "price_equal")

        Returns:
            DomainAction configured for accepting an offer
        """
        return DomainAction(
            action_type=ActionType.ACCEPT_OFFER,
            parameters={
                "order_id": self.data.get("their_order_id"),
                "negotiation_id": self.data.get("negotiation_id"),
                "reason": reason,
                "our_price": self.data.get("our_price"),
                "their_price": self.data.get("their_price"),
                "our_order_id": self.data.get("our_order_id"),
                "their_order_id": self.data.get("their_order_id"),
            },
        )

    def reject(self, reason: str) -> DomainAction:
        """Build REJECT_OFFER action.

        Args:
            reason: Human-readable reason for rejecting (e.g., "invalid_data", "price_too_low")

        Returns:
            DomainAction configured for rejecting an offer
        """
        return DomainAction(
            action_type=ActionType.REJECT_OFFER,
            parameters={
                "order_id": self.data.get("their_order_id"),
                "negotiation_id": self.data.get("negotiation_id"),
                "reason": reason,
            },
        )

    def counter(self, proposed_price: int) -> DomainAction:
        """Build COUNTER_OFFER action.

        Args:
            proposed_price: The counter-offer price to propose

        Returns:
            DomainAction configured for making a counter-offer
        """
        return DomainAction(
            action_type=ActionType.COUNTER_OFFER,
            parameters={
                "order_id": self.data.get("their_order_id"),
                "negotiation_id": self.data.get("negotiation_id"),
                "proposed_price": proposed_price,
                "our_price": self.data.get("our_price"),
                "their_price": self.data.get("their_price"),
                "our_order_id": self.data.get("our_order_id"),
                "their_order_id": self.data.get("their_order_id"),
            },
        )

    def exit(self, reason: str) -> DomainAction:
        """Build EXIT_NEGOTIATION action.

        Args:
            reason: Human-readable reason for exiting (e.g., "timeout", "max_rounds", "stale")

        Returns:
            DomainAction configured for exiting negotiation
        """
        return DomainAction(
            action_type=ActionType.EXIT_NEGOTIATION,
            parameters={
                "order_id": self.data.get("their_order_id"),
                "negotiation_id": self.data.get("negotiation_id"),
                "reason": reason,
            },
        )


@dataclass
class ResourceActionBuilder:
    """Builder for resource-related actions (offers, requests, etc.).

    Example usage:
        resources = ResourceActionBuilder(context)
        return resources.make_offer(order_details)
    """

    context: Any  # DecisionContext, but avoiding circular import

    def make_offer(self, order_details: dict[str, Any]) -> DomainAction:
        """Build MAKE_OFFER action.

        Args:
            order_details: Dictionary containing offer details

        Returns:
            DomainAction configured for making an offer
        """
        return DomainAction(
            action_type=ActionType.MAKE_OFFER,
            parameters=order_details,
        )

    def cancel_offer(self, order_id: str, reason: str) -> DomainAction:
        """Build CANCEL_OFFER action.

        Args:
            order_id: ID of the order to cancel
            reason: Reason for cancellation

        Returns:
            DomainAction configured for canceling an offer
        """
        return DomainAction(
            action_type=ActionType.CANCEL_OFFER,
            parameters={
                "order_id": order_id,
                "reason": reason,
            },
        )


@dataclass
class CounterOfferParams:
    """Parameters for counter_offer action with validation.

    This dataclass provides type-safe parameter extraction and validation
    for the counter_offer action executor function.

    Example usage:
        params = CounterOfferParams.from_dict(parameters)
        if not params:
            return {"status": "error", "message": "Missing required parameters"}

        # Use params.negotiation_id, params.order_id, etc.
    """

    negotiation_id: str
    order_id: str  # Their order ID
    proposed_price: int
    our_price: int
    their_price: int
    our_order_id: str | None = None

    @classmethod
    def from_dict(cls, params: dict[str, Any]) -> "CounterOfferParams | None":
        """Create from parameters dict with validation.

        Args:
            params: Dictionary of parameters from action executor

        Returns:
            CounterOfferParams instance if all required parameters present, None otherwise
        """
        try:
            return cls(
                negotiation_id=params["negotiation_id"],
                order_id=params["order_id"],
                proposed_price=params["proposed_price"],
                our_price=params["our_price"],
                their_price=params["their_price"],
                our_order_id=params.get("our_order_id"),
            )
        except KeyError as e:
            logger.error(f"Missing required parameter for counter_offer: {e}")
            return None
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid parameter type for counter_offer: {e}")
            return None
